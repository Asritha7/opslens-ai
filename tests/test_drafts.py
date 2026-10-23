"""Draft input, HTTP ownership, and isolated PostgreSQL privilege checks."""
import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import Mock, patch

import psycopg
from psycopg import sql
from fastapi.testclient import TestClient

from runreviq.api import create_app, initialize_keys, read_keys
from runreviq.drafts import (prepare_draft, create_draft, list_drafts, get_draft,
                            connect_drafts, scope, owner_key, DraftLimit, DraftInputError, save_review, validate_review, ReviewConflict)

CONTENT = '# New runbook\n\n## Applicability\nservice: identity-service\nenvironment: production\nversion_min: 2.4.0\nversion_max_exclusive: 2.5.0\nkey_rotation_enabled: true\n'


class DraftInputTests(unittest.TestCase):
    def test_proposal_cannot_grant_authority(self):
        proposal = prepare_draft('example.md', CONTENT + 'allowed_roles: platform\nstatus: approved\nmetadata_verified: true\n')
        self.assertTrue(proposal['review_required'])
        self.assertFalse({'allowed_roles', 'status', 'metadata_verified'} & proposal['proposed_metadata'].keys())
        self.assertEqual(proposal['proposed_metadata']['service'], 'identity-service')
        self.assertEqual(proposal['provenance']['service'][0]['line'], 4)

    def test_rejects_paths_binary_empty_and_oversized_input(self):
        for filename, content in (('../a.md', CONTENT), ('/a.md', CONTENT), ('a.txt', CONTENT), ('a.md', ''), ('a.md', ' \n'), ('a.md', '\x00'), ('a.md', 'x'*1_000_001)):
            with self.subTest(filename=filename, size=len(content)), self.assertRaises(ValueError):
                prepare_draft(filename, content)

    def test_byte_limit_and_unicode(self):
        self.assertTrue(prepare_draft('unicode.MD', '# Café\n')['review_required'])
        with self.assertRaises(ValueError):
            prepare_draft('large.md', 'é'*500001)

    def test_identity_namespaces_are_distinct(self):
        self.assertNotEqual(owner_key('demo', 'same'), owner_key('google', 'same'))


class DraftApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        path = Path(self.directory.name) / 'keys.json'; initialize_keys(path)
        records = read_keys(path)
        records.append({'subject': 'second-platform', 'role': 'platform', 'token': 'other-test-token-'*3})
        path.write_text(json.dumps(records))
        self.records = records
        self.writer = Mock(return_value={'status': 'draft', 'proposal': {'review_required': True}})
        self.lister = Mock(return_value=[]); self.reader = Mock(return_value=None)
        self.reviewer = Mock(return_value={'revision': 1, 'review_required': True})
        self.evidence = Mock(return_value=[])
        self.client = TestClient(create_app(oidc_file=None, key_file=path, draft_writer=self.writer,
            draft_lister=self.lister, draft_reader=self.reader, document_loader=self.evidence, review_writer=self.reviewer))
        self.addCleanup(self.client.close)
        self.headers = {'Authorization': 'Bearer ' + records[0]['token'], 'Content-Type': 'text/markdown'}

    def test_authentication_required_before_upload(self):
        self.assertEqual(self.client.post('/v1/drafts?filename=a.md', content=CONTENT).status_code, 401)
        self.assertEqual(self.client.get('/v1/drafts').status_code, 401)
        self.writer.assert_not_called(); self.lister.assert_not_called()

    def test_owner_comes_from_identity_not_role_or_query(self):
        for record in (next(r for r in self.records if r['subject'] == 'demo-platform'), self.records[-1]):
            response = self.client.post('/v1/drafts?filename=a.md&owner=someone-else', content=CONTENT,
                headers={**self.headers, 'Authorization': 'Bearer ' + record['token']})
            self.assertEqual(response.status_code, 201)
            self.assertEqual(self.writer.call_args.args[0], owner_key('demo', record['subject']))
        self.assertNotEqual(self.writer.call_args_list[0].args[0], self.writer.call_args_list[1].args[0])
        self.evidence.assert_not_called()

    def test_transport_limits_and_encoding(self):
        for data, headers, expected in ((b'x'*1_000_001, self.headers, 413), (b'\xff', self.headers, 422),
                                       (CONTENT, {**self.headers, 'Content-Type':'application/json'}, 415)):
            with self.subTest(expected=expected):
                self.assertEqual(self.client.post('/v1/drafts?filename=a.md', content=data, headers=headers).status_code, expected)
        self.writer.assert_not_called()

    def test_safe_errors_and_quota(self):
        for error, status in ((DraftLimit(), 429), (DraftInputError('private-input'), 422), (psycopg.OperationalError('secret'), 503), (ValueError('private config'), 503)):
            self.writer.side_effect = error
            response = self.client.post('/v1/drafts?filename=a.md', content=CONTENT, headers=self.headers)
            self.assertEqual(response.status_code, status)
            self.assertNotIn(str(error), response.text) if str(error) else None

    def test_lists_own_drafts_and_uses_uniform_not_found(self):
        self.assertEqual(self.client.get('/v1/drafts', headers=self.headers).json(), {'drafts': []})
        self.assertEqual(self.lister.call_args.args[0], owner_key('demo', self.records[0]['subject']))
        for _ in range(2):
            response = self.client.get('/v1/drafts/' + str(uuid.uuid4()), headers=self.headers)
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json(), {'detail':'Draft not found'})
        self.assertEqual(self.client.get('/v1/drafts/not-a-uuid', headers=self.headers).status_code, 422)

    def test_review_auth_validation_and_ownership(self):
        url = '/v1/drafts/' + str(uuid.uuid4()) + '/review'
        metadata = dict.fromkeys(('title', 'service', 'environment', 'version_min', 'version_max_exclusive', 'key_rotation_enabled'), '')
        body = {'expected_revision': 0, 'metadata': metadata}
        self.assertEqual(self.client.post(url, json=body).status_code, 401)
        headers = {'Authorization': self.headers['Authorization']}
        self.assertEqual(self.client.post(url, json=body, headers=headers).status_code, 200)
        self.assertEqual(self.reviewer.call_args.args[0], owner_key('demo', self.records[0]['subject']))
        for invalid in ({**body, 'approved': True}, {**body, 'expected_revision': True},
                        {**body, 'metadata': {**metadata, 'allowed_roles': 'platform'}}):
            self.assertEqual(self.client.post(url, json=invalid, headers=headers).status_code, 422)

    def test_review_conflict_missing_and_storage_errors(self):
        url = '/v1/drafts/' + str(uuid.uuid4()) + '/review'
        body = {'expected_revision': 0, 'metadata': dict.fromkeys(('title', 'service', 'environment', 'version_min', 'version_max_exclusive', 'key_rotation_enabled'), '')}
        headers = {'Authorization': self.headers['Authorization']}
        for error, status in ((ReviewConflict(), 409), (psycopg.OperationalError('secret'), 503)):
            self.reviewer.side_effect = error
            response = self.client.post(url, json=body, headers=headers)
            self.assertEqual(response.status_code, status); self.assertNotIn('secret', response.text)
        self.reviewer.side_effect = None; self.reviewer.return_value = None
        self.assertEqual(self.client.post(url, json=body, headers=headers).status_code, 404)


@unittest.skipUnless(os.environ.get('RUNREVIQ_TEST_DATABASE') == '1', 'Requires disposable PostgreSQL database')
class DraftDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from runreviq.database import connect, bootstrap
        cls.dbname = 'opslens_test_' + uuid.uuid4().hex
        with connect(dbname='postgres', autocommit=True) as conn:
            conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(cls.dbname)))
        cls.addClassCleanup(cls.drop_database)
        bootstrap(cls.dbname)

    @classmethod
    def drop_database(cls):
        from runreviq.database import connect
        assert cls.dbname.startswith('opslens_test_')
        with connect(dbname='postgres', autocommit=True) as conn:
            conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(cls.dbname)))

    def setUp(self):
        self.owner = owner_key('google', uuid.uuid4().hex)
        self.other = owner_key('google', uuid.uuid4().hex)

    def save(self):
        return create_draft(self.owner, 'example.md', CONTENT, dbname=self.dbname)

    def test_saved_draft_survives_new_connection_and_is_private(self):
        draft = self.save()
        stored = get_draft(self.owner, draft['id'], dbname=self.dbname)
        self.assertEqual(stored['content'], CONTENT)
        self.assertTrue(stored['proposal']['review_required'])
        self.assertEqual(list_drafts(self.owner, dbname=self.dbname)[0]['id'], draft['id'])
        self.assertEqual(list_drafts(self.other, dbname=self.dbname), [])
        self.assertIsNone(get_draft(self.other, draft['id'], dbname=self.dbname))

    def test_no_owner_context_sees_nothing_and_cannot_insert(self):
        self.save()
        with connect_drafts(self.dbname) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM opslens.upload_drafts').fetchone()[0], 0)
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                conn.execute("INSERT INTO opslens.upload_drafts VALUES (%s,%s,'a.md','text','{}',now())", (uuid.uuid4(), self.owner))

    def test_owner_policy_rejects_mismatched_insert(self):
        with connect_drafts(self.dbname) as conn:
            scope(conn, self.owner)
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                conn.execute("INSERT INTO opslens.upload_drafts VALUES (%s,%s,'a.md','text','{}',now())", (uuid.uuid4(), self.other))

    def test_draft_login_cannot_read_publish_edit_or_assume_role(self):
        self.save()
        for statement in ('SELECT * FROM opslens.documents', 'SELECT * FROM opslens.document_versions',
                          "INSERT INTO opslens.documents VALUES ('BAD-001',1,'{}')", 'DELETE FROM opslens.upload_drafts',
                          "UPDATE opslens.upload_drafts SET content='changed'", 'SET ROLE opslens_reader_platform'):
            with self.subTest(statement=statement), connect_drafts(self.dbname) as conn:
                scope(conn, self.owner)
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    conn.execute(statement)

    def test_evidence_reader_cannot_read_drafts(self):
        from runreviq.database import connect
        self.save()
        with connect(role='platform', dbname=self.dbname) as conn:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                conn.execute('SELECT * FROM opslens.upload_drafts')

    def test_quota_is_per_owner(self):
        with patch('runreviq.drafts.MAX_DRAFTS', 2):
            self.save(); self.save()
            with self.assertRaises(DraftLimit): self.save()
            create_draft(self.other, 'other.md', CONTENT, dbname=self.dbname)

    def test_drafts_do_not_enter_selector_and_bootstrap_preserves_them(self):
        from runreviq.database import load_authorized_documents, bootstrap
        self.save(); bootstrap(self.dbname)
        self.assertEqual(len(list_drafts(self.owner, dbname=self.dbname)), 1)
        self.assertEqual(load_authorized_documents('platform', dbname=self.dbname), [])


    def test_review_persistence_conflict_and_original_preservation(self):
        draft = self.save()
        metadata = {'title': 'Corrected title', 'service': 'identity-service', 'environment': 'staging',
                    'version_min': '2.4.0', 'version_max_exclusive': '2.5.0', 'key_rotation_enabled': 'none'}
        review = save_review(self.owner, draft['id'], 0, metadata, dbname=self.dbname)
        self.assertEqual(review['revision'], 1); self.assertEqual(review['issues'], [])
        stored = get_draft(self.owner, draft['id'], dbname=self.dbname)
        self.assertEqual(stored['content'], CONTENT); self.assertEqual(stored['proposal'], draft['proposal'])
        self.assertEqual(stored['review']['metadata'], metadata)
        with self.assertRaises(ReviewConflict): save_review(self.owner, draft['id'], 0, metadata, dbname=self.dbname)
        self.assertIsNone(save_review(self.other, draft['id'], 1, metadata, dbname=self.dbname))
        self.assertIsNone(get_draft(self.other, draft['id'], dbname=self.dbname))
        metadata['environment'] = ''
        saved = save_review(self.owner, draft['id'], 1, metadata, dbname=self.dbname)
        self.assertEqual(saved['revision'], 2); self.assertIn({'field':'environment','reason':'missing'}, saved['issues'])
        with connect_drafts(self.dbname) as conn:
            scope(conn, self.owner)
            self.assertEqual(conn.execute('SELECT count(*) FROM opslens.draft_reviews WHERE draft_id=%s', (draft['id'],)).fetchone()[0], 2)

    def test_review_rls_and_append_only_grants(self):
        draft = self.save()
        for owner, statement in ((self.other, "INSERT INTO opslens.draft_reviews VALUES (%s,1,'{}',now())"),
                                 (self.owner, 'DELETE FROM opslens.draft_reviews WHERE draft_id=%s'),
                                 (self.owner, "UPDATE opslens.draft_reviews SET metadata='{}' WHERE draft_id=%s")):
            with connect_drafts(self.dbname) as conn:
                scope(conn, owner)
                with self.assertRaises(psycopg.errors.InsufficientPrivilege): conn.execute(statement, (draft['id'],))


class ReviewValidationTests(unittest.TestCase):
    def test_incomplete_invalid_and_inverted_fields_are_visible(self):
        metadata = {'title':'', 'service':'bad service', 'environment':'prod', 'version_min':'3.0.0',
                    'version_max_exclusive':'2.0.0', 'key_rotation_enabled':'unknown'}
        result = validate_review(metadata)
        self.assertEqual(len(result['issues']), 5)
        self.assertTrue(result['review_required']); self.assertEqual(result['status'], 'in_progress')
        self.assertNotIn('version_min', result['validated_metadata'])
        for bad in ({**metadata, 'approved':True}, {**metadata, 'title':'x'*201}, {**metadata, 'title':'a\x00b'}):
            with self.assertRaises(DraftInputError): validate_review(bad)
