import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import psycopg
from psycopg import sql
from fastapi.testclient import TestClient

from runreviq import publications as pub
from runreviq.api import create_app, initialize_keys, read_keys
from runreviq.database import connect, bootstrap, load_authorized_documents, load_authorized_revision
from runreviq.drafts import create_draft, save_review, owner_key, ReviewConflict, DraftInputError
from runreviq.submissions import submit, decide, own_submissions, connect_reviewer
from runreviq.selector import select

META = dict(title='Example',service='identity-service',environment='staging',version_min='2.4.0',version_max_exclusive='2.5.0',key_rotation_enabled='none')
CLAIMS = [dict(action='rotate_keys',rule='must',start_line=2,end_line=2)]
SOURCE = '# Example\nYou must rotate keys.\n'


class PublicationApiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name); self.allow=root/'publishers.json'
        keys=root/'keys.json';initialize_keys(keys);records=read_keys(keys)
        self.subject=records[0]['subject'];self.headers={'Authorization':'Bearer '+records[0]['token']}
        self.client=TestClient(create_app(key_file=keys,oidc_file=None,publishers_file=self.allow));self.addCleanup(self.client.close)
        self.url='/v1/publications/'+str(uuid.uuid4())
        self.body=dict(allowed_roles=['platform'],claims=CLAIMS,metadata_verified=True)

    def grant(self):
        self.allow.write_text(json.dumps({'demo':[self.subject],'google':[]}));self.allow.chmod(0o600)

    def test_denied_by_default_and_revoked_each_request(self):
        with patch('runreviq.publications.queue',return_value=[]) as loader:
            self.assertEqual(self.client.get('/v1/publications/queue',headers=self.headers).status_code,403)
            self.assertEqual(self.client.get('/v1/publisher-access',headers=self.headers).json(),{'can_publish':False})
            self.grant()
            self.assertEqual(self.client.get('/v1/publications/queue',headers=self.headers).status_code,200)
            self.allow.unlink()
            self.assertEqual(self.client.get('/v1/publications/queue',headers=self.headers).status_code,403)
            self.assertEqual(loader.call_count,1)

    def test_actor_schema_and_authentication(self):
        self.grant()
        with patch('runreviq.publications.publish',return_value={'published':True}) as publish:
            self.assertEqual(self.client.post(self.url,json=self.body).status_code,401)
            self.assertEqual(self.client.post(self.url,json={**self.body,'publisher':'fake'},headers=self.headers).status_code,422)
            self.assertEqual(self.client.post(self.url,json=self.body,headers=self.headers).status_code,200)
            self.assertEqual(publish.call_args.args[0],owner_key('demo',self.subject))

    def test_errors_are_sanitized(self):
        self.grant()
        for error,code in [(DraftInputError('secret'),422),(ReviewConflict(),409),(psycopg.OperationalError('secret'),503)]:
            with patch('runreviq.publications.publish',side_effect=error):
                response=self.client.post(self.url,json=self.body,headers=self.headers)
                self.assertEqual(response.status_code,code);self.assertNotIn('secret',response.text)

    def test_claim_validation_and_exact_quote(self):
        claim=pub.prepare_claims(CLAIMS,SOURCE)[0]
        self.assertEqual(claim['citation']['quote'],'You must rotate keys.')
        for claims in ([],CLAIMS*2,[{**CLAIMS[0],'end_line':99}],[{**CLAIMS[0],'start_line':True}],[{**CLAIMS[0],'action':'bad action'}]):
            with self.assertRaises(DraftInputError):pub.prepare_claims(claims,SOURCE)


@unittest.skipUnless(os.environ.get('RUNREVIQ_TEST_DATABASE')=='1','Requires disposable PostgreSQL')
class PublicationDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dbname='opslens_test_'+uuid.uuid4().hex
        with connect(dbname='postgres',autocommit=True) as conn:
            conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(cls.dbname)))
        cls.addClassCleanup(cls.drop_database);bootstrap(cls.dbname)

    @classmethod
    def drop_database(cls):
        with connect(dbname='postgres',autocommit=True) as conn:
            conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(cls.dbname)))

    def setUp(self):
        assert self.dbname.startswith('opslens_test_')
        with connect(dbname=self.dbname) as conn:
            conn.execute('TRUNCATE opslens.document_withdrawals, opslens.publications, opslens.document_versions, opslens.documents, opslens.submission_decisions, opslens.draft_submissions, opslens.draft_reviews, opslens.upload_drafts')
        self.owner=owner_key('demo',uuid.uuid4().hex);self.reviewer=owner_key('demo','reviewer');self.publisher=owner_key('demo','publisher')
        self.draft=create_draft(self.owner,'example.md',SOURCE,dbname=self.dbname)
        self.sub=self.round(0)

    def round(self,previous,decision='approved'):
        save_review(self.owner,self.draft['id'],previous,META,dbname=self.dbname)
        sub=submit(self.owner,self.draft['id'],previous+1,dbname=self.dbname)
        if decision:decide(self.reviewer,sub['id'],decision,'Checked source',dbname=self.dbname)
        return sub

    def publish(self,sub=None,roles=None,claims=None,verified=True):
        return pub.publish(self.publisher,(sub or self.sub)['id'],roles or ['platform'],claims if claims is not None else CLAIMS,verified,dbname=self.dbname)

    def test_publication_is_cited_and_role_scoped(self):
        self.assertFalse(any(d['id']=='UPLOAD-'+str(uuid.UUID(self.draft['id']).int) for d in load_authorized_documents('platform',dbname=self.dbname)))
        result=self.publish();identifier=result['document_id']
        documents=load_authorized_documents('platform',dbname=self.dbname)
        selected=select(documents,role='platform',service='identity-service',software_version='2.4.0',environment='staging')
        self.assertIn(identifier,selected['recommended_documents'])
        self.assertIsNone(load_authorized_revision('intern',identifier,1,dbname=self.dbname))
        self.assertEqual(load_authorized_revision('platform',identifier,1,dbname=self.dbname)['content'],SOURCE)
        history=own_submissions(self.owner,self.draft['id'],dbname=self.dbname)
        self.assertEqual(history[0]['publication']['document_id'],identifier)
        from runreviq.submissions import submission_detail
        self.assertTrue(submission_detail(self.reviewer,self.sub['id'],dbname=self.dbname)['published'])
        self.assertTrue(submit(self.owner,self.draft['id'],1,dbname=self.dbname)['published'])
        self.assertEqual(own_submissions(self.reviewer,self.draft['id'],dbname=self.dbname),None)

    def test_only_approved_snapshots_and_later_edits_excluded(self):
        pending=self.round(1,None)
        self.assertIsNone(self.publish(pending))
        self.assertIsNone(pub.detail(pending['id'],dbname=self.dbname))
        with pub.connect_publisher(self.dbname) as conn:
            self.assertEqual(conn.execute('SELECT revision FROM opslens.draft_reviews WHERE draft_id=%s',(self.draft['id'],)).fetchall(),[(1,)])
        result=self.publish()
        self.assertEqual(result['revision'],1)
        self.assertEqual(pub.detail(self.sub['id'],dbname=self.dbname)['metadata'],META)
        changes=self.round(2,'changes_requested');self.assertIsNone(self.publish(changes))

    def test_invalid_publication_rolls_back(self):
        for kwargs in ({'claims':[]},{'verified':False},{'claims':[{**CLAIMS[0],'end_line':999}]},{'roles':['platform','platform']}):
            with self.assertRaises(DraftInputError):self.publish(**kwargs)
        with pub.connect_publisher(self.dbname) as conn:
            self.assertIsNone(conn.execute('SELECT 1 FROM opslens.publications WHERE submission_id=%s',(self.sub['id'],)).fetchone())
        self.publish()

    def test_retry_is_idempotent_and_changed_settings_conflict(self):
        first=self.publish();self.assertEqual(first,self.publish())
        with self.assertRaises(ReviewConflict):self.publish(roles=['security'])
        with self.assertRaises(ReviewConflict):self.publish(claims=[{**CLAIMS[0],'rule':'must_not'}])

    def test_new_revision_preserves_history_and_current_permissions(self):
        first=self.publish();second=self.round(1);self.publish(second,roles=['security'])
        self.assertIsNone(load_authorized_revision('platform',first['document_id'],1,dbname=self.dbname))
        old=load_authorized_revision('security',first['document_id'],1,dbname=self.dbname)
        self.assertEqual(old['content'],SOURCE);self.assertFalse(old['is_current'])

    def test_newer_publication_blocks_older_and_queue_omits_stale(self):
        second=self.round(1);self.publish(second)
        with self.assertRaises(ReviewConflict):self.publish()
        self.assertNotIn(self.sub['id'],[s['id'] for s in pub.queue(dbname=self.dbname)])

    def test_concurrent_retry_produces_one_publication(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.publish(),range(2)))
        self.assertEqual(results[0],results[1])

    def test_opposing_published_claims_surface_conflict_with_citations(self):
        first=self.publish()
        other=create_draft(self.owner,'opposing.md','# Opposing\nDo not rotate keys.\n',dbname=self.dbname)
        save_review(self.owner,other['id'],0,META,dbname=self.dbname)
        other_sub=submit(self.owner,other['id'],1,dbname=self.dbname)
        decide(self.reviewer,other_sub['id'],'approved','Checked',dbname=self.dbname)
        second=self.publish(other_sub,claims=[{**CLAIMS[0],'rule':'must_not'}])
        result=select(load_authorized_documents('platform',dbname=self.dbname),role='platform',service='identity-service',software_version='2.4.0',environment='staging')
        pair={first['document_id'],second['document_id']}
        self.assertEqual(result['status'],'conflict')
        self.assertTrue(any(set(p)==pair for p in result['conflicts']))
        self.assertTrue(all(d['citation_status']=='available' for c in result['conflict_details'] for d in c['documents']))

    def test_withdrawn_publication_retry_stays_withdrawn_and_new_approval_replaces_it(self):
        from runreviq import lifecycle
        first=self.publish()
        lifecycle.withdraw(self.publisher,first['document_id'],1,'Outdated',dbname=self.dbname)
        self.assertEqual(first,self.publish())
        self.assertNotIn(first['document_id'],[d['id'] for d in load_authorized_documents('platform',dbname=self.dbname)])
        second=self.round(1);self.publish(second)
        self.assertIn(first['document_id'],[d['id'] for d in load_authorized_documents('platform',dbname=self.dbname)])
        history=lifecycle.history(first['document_id'],dbname=self.dbname)
        self.assertEqual([r['status'] for r in history['revisions']],['active','withdrawn'])

    def test_reviewer_cannot_publish_and_publisher_cannot_decide_or_delete(self):
        with connect_reviewer(self.dbname) as conn,self.assertRaises(psycopg.errors.InsufficientPrivilege):
            conn.execute('SELECT publisher FROM opslens.publications')
        for command in ('DELETE FROM opslens.documents','DELETE FROM opslens.publications',"UPDATE opslens.document_versions SET content='changed'",'SET ROLE opslens_review_operator',"DELETE FROM opslens.submission_decisions"):
            with pub.connect_publisher(self.dbname) as conn,self.assertRaises(psycopg.errors.InsufficientPrivilege):conn.execute(command)
