"""Opt-in integration tests; all test writes use a fresh disposable database."""
import copy
import os
import unittest
import uuid

from runreviq.selector import load_documents, select


@unittest.skipUnless(os.environ.get('RUNREVIQ_TEST_DATABASE') == '1', 'Set RUNREVIQ_TEST_DATABASE=1 for local DB integration tests')
class DatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from runreviq.database import connect, bootstrap
        from psycopg import sql
        cls.dbname = 'opslens_test_' + uuid.uuid4().hex
        with connect(dbname='postgres', autocommit=True) as conn:
            conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(cls.dbname)))
        cls.addClassCleanup(cls.drop_database)
        bootstrap(cls.dbname)

    @classmethod
    def drop_database(cls):
        from runreviq.database import connect
        from psycopg import sql
        assert cls.dbname.startswith('opslens_test_')
        with connect(dbname='postgres', autocommit=True) as conn:
            conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(cls.dbname)))

    def setUp(self):
        from runreviq.database import connect, ingest
        # This database was created by this test class, never the development database.
        with connect(dbname=self.dbname) as conn:
            conn.execute('TRUNCATE opslens.document_versions, opslens.documents')
        self.docs = load_documents()
        ingest(self.docs, dbname=self.dbname)

    def test_file_database_parity(self):
        from runreviq.database import load_authorized_documents
        for role in ('platform', 'security', 'intern'):
            for ver in ('2.1.0', '2.4.0', '2.5.0', '2.6.0'):
                for env in ('production', 'staging'):
                    for rotation in (True, False, None):
                        with self.subTest(role=role, version=ver, environment=env, rotation=rotation):
                            args = dict(role=role, service='identity-service', software_version=ver,
                                        environment=env, key_rotation_enabled=rotation)
                            self.assertEqual(select(self.docs, **args), select(load_authorized_documents(role, dbname=self.dbname), **args))

    def test_authenticated_http_uses_real_database_roles(self):
        import tempfile
        from pathlib import Path
        from fastapi.testclient import TestClient
        from runreviq.api import create_app, initialize_keys, read_keys
        from runreviq.database import load_authorized_documents
        from test_api import QUERY
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'keys.json'
            initialize_keys(path)
            loader = lambda role: load_authorized_documents(role, dbname=self.dbname)
            with TestClient(create_app(oidc_file=None, key_file=path, document_loader=loader)) as client:
                for record in read_keys(path):
                    headers = {'Authorization': 'Bearer ' + record['token']}
                    for environment in ('production', 'staging'):
                        query = dict(QUERY, environment=environment)
                        response = client.post('/v1/select', json=query, headers=headers)
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(response.json(), select(self.docs, role=record['role'], **query))
                        if record['role'] != 'security':
                            self.assertNotIn('SEC-021', response.text)

    def test_revision_http_history_and_current_permission_revocation(self):
        import tempfile
        from pathlib import Path
        from fastapi.testclient import TestClient
        from runreviq.api import create_app, initialize_keys, read_keys
        from runreviq.database import ingest, load_authorized_revision, prepare
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'keys.json'
            initialize_keys(path)
            headers = {r['role']: {'Authorization': 'Bearer ' + r['token']} for r in read_keys(path)}
            loader = lambda role, doc, rev: load_authorized_revision(role, doc, rev, dbname=self.dbname)
            with TestClient(create_app(oidc_file=None, key_file=path, revision_loader=loader)) as client:
                url = '/v1/documents/RB-042/revisions/'
                original = client.get(url + '1', headers=headers['platform'])
                self.assertEqual(original.status_code, 200)
                record = original.json()
                prepared = prepare([self.docs[1]])[0]
                self.assertEqual(record['content'], prepared[2])
                self.assertEqual(record['checksum'], prepared[3])
                self.assertEqual(record['title'], self.docs[1]['title'])
                self.assertTrue(record['is_current'])
                hidden = client.get(url + '1', headers=headers['intern'])
                missing = client.get('/v1/documents/RB-999/revisions/1', headers=headers['intern'])
                absent_revision = client.get(url + '99', headers=headers['platform'])
                self.assertEqual(hidden.status_code, 404)
                self.assertEqual(missing.status_code, 404)
                self.assertEqual(absent_revision.status_code, 404)
                self.assertEqual(hidden.json(), missing.json())
                self.assertEqual(hidden.json(), absent_revision.json())
                self.assertEqual(client.get('/v1/documents/SEC-021/revisions/1', headers=headers['security']).status_code, 200)
                self.assertEqual(client.get('/v1/documents/SEC-021/revisions/1', headers=headers['platform']).status_code, 404)
                newer = copy.deepcopy(self.docs[1])
                newer.update(revision=2, title='Reviewed revision two')
                ingest([newer], dbname=self.dbname)
                old = client.get(url + '1', headers=headers['platform']).json()
                self.assertEqual(old['content'], record['content'])
                self.assertEqual(old['checksum'], record['checksum'])
                self.assertFalse(old['is_current'])
                self.assertEqual(old['current_revision'], 2)
                self.assertEqual(client.get(url + '2', headers=headers['platform']).json()['title'], newer['title'])
                newer['allowed_roles'] = ['security']
                ingest([newer], dbname=self.dbname)
                for rev in ('1', '2'):
                    self.assertEqual(client.get(url + rev, headers=headers['platform']).status_code, 404)
                    self.assertEqual(client.get(url + rev, headers=headers['security']).status_code, 200)
                newer.update(revision=3, status='revoked')
                ingest([newer], dbname=self.dbname)
                for role_headers in headers.values():
                    for rev in ('1', '2', '3'):
                        response = client.get(url + rev, headers=role_headers)
                        self.assertEqual(response.status_code, 404)
                        self.assertEqual(response.json(), missing.json())

    def test_citations_publish_new_revision_and_preserve_legacy_evidence(self):
        from runreviq.database import ingest, connect, load_authorized_documents, load_authorized_revision
        from runreviq.citations import validate_citations
        current = next(d for d in self.docs if d['id'] == 'RB-050')
        legacy = copy.deepcopy(current)
        legacy['revision'] = 1
        legacy['claims'][0].pop('citation')
        ingest([legacy], dbname=self.dbname)
        with connect(dbname=self.dbname) as conn:
            old = conn.execute("SELECT metadata FROM opslens.document_versions WHERE document_id='RB-050' AND revision=1").fetchone()[0]
            self.assertNotIn('citation', old['claims'][0])
        loaded = next(d for d in load_authorized_documents('platform', dbname=self.dbname) if d['id'] == 'RB-050')
        stored = load_authorized_revision('platform', 'RB-050', 2, dbname=self.dbname)
        validate_citations(loaded['claims'], stored['content'])
        self.assertEqual(loaded['revision'], 2)
        self.assertEqual(loaded['claims'], current['claims'])
        self.assertIsNotNone(load_authorized_revision('platform', 'RB-050', 1, dbname=self.dbname))

    def test_bad_citation_batch_does_not_publish(self):
        from runreviq.database import ingest, connect
        good = copy.deepcopy(self.docs[0])
        good['id'] = 'RB-999'
        bad = copy.deepcopy(next(d for d in self.docs if d['id'] == 'RB-050'))
        bad['revision'] = 3
        bad['claims'][0]['citation']['quote'] = 'Invented quote'
        with self.assertRaises(ValueError):
            ingest([good, bad], dbname=self.dbname)
        with connect(dbname=self.dbname) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM opslens.documents WHERE id='RB-999'").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT current_revision FROM opslens.documents WHERE id='RB-050'").fetchone()[0], 2)

    def test_repeat_ingestion_is_noop(self):
        from runreviq.database import ingest
        self.assertEqual(ingest(self.docs, dbname=self.dbname)['versions_inserted'], 0)

    def test_raw_reader_cannot_see_restricted_sources(self):
        from runreviq.database import connect
        with connect(role='intern', dbname=self.dbname) as conn:
            ids = conn.execute('SELECT document_id FROM opslens.document_versions ORDER BY document_id').fetchall()
            self.assertEqual(ids, [('RB-044',)])
        with connect(role='platform', dbname=self.dbname) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM opslens.document_versions WHERE document_id IN ('SEC-021','RB-070')").fetchone()[0], 0)

    def test_reader_is_not_privileged(self):
        from runreviq.database import connect
        with connect(role='platform', dbname=self.dbname) as conn:
            self.assertEqual(conn.execute('SELECT rolsuper, rolcreatedb, rolcreaterole, rolbypassrls FROM pg_roles WHERE rolname=current_user').fetchone(), (False, False, False, False))

    def test_reader_cannot_write_or_assume_other_persona(self):
        import psycopg
        from runreviq.database import connect
        for statement in ("UPDATE opslens.documents SET allowed_roles=ARRAY['intern']", 'SET ROLE opslens_reader_security'):
            with self.subTest(statement=statement), self.assertRaises(psycopg.errors.InsufficientPrivilege):
                with connect(role='intern', dbname=self.dbname) as conn:
                    conn.execute(statement)

    def test_same_revision_changes_roll_back_whole_batch(self):
        from runreviq.database import connect, ingest
        new = copy.deepcopy(self.docs[0])
        new['id'] = 'RB-999'
        changed = copy.deepcopy(self.docs[1])
        changed['title'] = 'Changed without a revision bump'
        with self.assertRaises(ValueError):
            ingest([new, changed], dbname=self.dbname)
        with connect(dbname=self.dbname) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM opslens.documents WHERE id='RB-999'").fetchone()[0], 0)

    def test_new_revision_preserves_history_and_stale_upload_cannot_replace_it(self):
        from runreviq.database import connect, ingest
        newer = copy.deepcopy(self.docs[1])
        newer.update(revision=2, title='Reviewed revision two', allowed_roles=['security'])
        ingest([newer], dbname=self.dbname)
        ingest([self.docs[1]], dbname=self.dbname)
        with connect(dbname=self.dbname) as conn:
            self.assertEqual(conn.execute("SELECT current_revision,allowed_roles FROM opslens.documents WHERE id='RB-042'").fetchone(), (2, ['security']))
            rows = conn.execute("SELECT revision,metadata->>'title',length(content) FROM opslens.document_versions WHERE document_id='RB-042' ORDER BY revision").fetchall()
            self.assertEqual([r[0] for r in rows], [1, 2])
            self.assertEqual(rows[0][1], self.docs[1]['title'])
            self.assertGreater(rows[0][2], 0)
        with connect(role='platform', dbname=self.dbname) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM opslens.document_versions WHERE document_id='RB-042'").fetchone()[0], 0)

    def test_permission_changes_apply_to_existing_revision(self):
        from runreviq.database import ingest, load_authorized_documents
        changed = copy.deepcopy(self.docs[1])
        changed['allowed_roles'] = ['security']
        self.assertEqual(ingest([changed], dbname=self.dbname)['versions_inserted'], 0)
        self.assertNotIn('RB-042', [d['id'] for d in load_authorized_documents('platform', dbname=self.dbname)])

    def test_database_rejects_in_place_revision_update(self):
        import psycopg
        from runreviq.database import connect
        with self.assertRaises(psycopg.errors.RaiseException):
            with connect(dbname=self.dbname) as conn:
                conn.execute("UPDATE opslens.document_versions SET content='changed' WHERE document_id='RB-042'")

    def test_migration_is_repeatable(self):
        from runreviq.database import bootstrap
        bootstrap(self.dbname)


class CatalogValidationTests(unittest.TestCase):
    def test_revision_reader_rejects_admin_or_invalid_inputs(self):
        from unittest.mock import patch
        from runreviq.database import load_authorized_revision
        with patch('runreviq.database.connect') as connect:
            for role, doc, rev in ((None, 'RB-042', 1), ('admin', 'RB-042', 1),
                                   ('platform', "RB-042' OR true", 1), ('platform', 'RB-042', True),
                                   ('platform', 'RB-042', 0), ('platform', 'RB-042', 2147483648)):
                with self.subTest(role=role, doc=doc, rev=rev), self.assertRaises(ValueError):
                    load_authorized_revision(role, doc, rev)
            connect.assert_not_called()

    def test_reject_invalid_catalog_before_ingestion(self):
        from runreviq.database import prepare
        for updates in ({'path': '../../.env'}, {'revision': 0}, {'revision': True},
                        {'allowed_roles': ['admin']}, {'version_min': '2.5.0', 'version_max_exclusive': '2.4.0'},
                        {'key_rotation_enabled': 'true'}, {'metadata_verified': 'true'}):
            with self.subTest(updates=updates):
                doc = copy.deepcopy(load_documents()[0])
                doc.update(updates)
                with self.assertRaises(ValueError):
                    prepare([doc])

    def test_duplicate_ids_rejected(self):
        from runreviq.database import prepare
        doc = load_documents()[0]
        with self.assertRaises(ValueError):
            prepare([doc, doc])
