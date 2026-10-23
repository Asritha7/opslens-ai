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

from runreviq.api import create_app, initialize_keys, read_keys
from runreviq.database import connect, bootstrap, load_authorized_documents
from runreviq.drafts import create_draft, save_review, owner_key, connect_drafts, scope, ReviewConflict, DraftInputError
from runreviq import submissions as workflow

METADATA = dict(title='Example', service='identity-service', environment='staging', version_min='2.4.0', version_max_exclusive='2.5.0', key_rotation_enabled='none')


class ReviewerAccessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'reviewers.json'

    def write(self, data):
        self.path.write_text(json.dumps(data)); self.path.chmod(0o600)

    def test_missing_and_separate_namespaces(self):
        self.assertFalse(workflow.can_review('google','a',self.path))
        self.write({'google':['a'],'demo':[]})
        self.assertTrue(workflow.can_review('google','a',self.path))
        self.assertFalse(workflow.can_review('demo','a',self.path))
        self.write({'google':[],'demo':[]})
        self.assertFalse(workflow.can_review('google','a',self.path))

    def test_malformed_or_readable_configuration_fails_closed(self):
        for bad in ({'google':['a']}, {'google':'a','demo':[]}, {'google':[1],'demo':[]}):
            self.write(bad)
            with self.assertRaises(ValueError): workflow.can_review('google','a',self.path)
        self.write({'google':['a'],'demo':[]}); self.path.chmod(0o644)
        with self.assertRaises(ValueError): workflow.can_review('google','a',self.path)

    def client(self):
        keys = Path(self.temp.name) / 'keys.json'; initialize_keys(keys)
        records = read_keys(keys)
        client = TestClient(create_app(key_file=keys,oidc_file=None,reviewers_file=self.path)); self.addCleanup(client.close)
        return client, records, {'Authorization':'Bearer '+records[0]['token']}

    def test_reading_role_does_not_grant_review_access(self):
        client,records,headers = self.client()
        self.assertEqual(client.get('/v1/reviewer-access',headers=headers).json(),{'can_review':False})
        with patch('runreviq.submissions.review_queue') as loader:
            self.assertEqual(client.get('/v1/submissions',headers=headers).status_code,403)
            loader.assert_not_called()
        self.assertEqual(client.get('/v1/submissions').status_code,401)

    def test_reviewer_revocation_and_identity_are_server_controlled(self):
        client,records,headers = self.client()
        self.write({'google':[],'demo':[records[0]['subject']]})
        with patch('runreviq.submissions.review_queue',return_value=[]) as loader:
            self.assertEqual(client.get('/v1/submissions?reviewer=other',headers=headers).status_code,200)
            loader.assert_called_with(owner_key('demo',records[0]['subject']))
            self.write({'google':[],'demo':[]})
            self.assertEqual(client.get('/v1/submissions',headers=headers).status_code,403)
            self.assertEqual(loader.call_count,1)

    def test_submission_errors_and_forbidden_authority_fields(self):
        client,records,headers = self.client(); url='/v1/drafts/'+str(uuid.uuid4())+'/submit'
        self.assertEqual(client.post(url,json={'revision':1,'approved':True},headers=headers).status_code,422)
        for error,status in ((ReviewConflict(),409),(DraftInputError(),422),(psycopg.OperationalError('private'),503)):
            with patch('runreviq.submissions.submit',side_effect=error):
                response=client.post(url,json={'revision':1},headers=headers)
                self.assertEqual(response.status_code,status); self.assertNotIn('private',response.text)
        with patch('runreviq.submissions.submit',return_value=None):
            self.assertEqual(client.post(url,json={'revision':1},headers=headers).status_code,404)

    def test_decision_access_schema_and_actor(self):
        client,records,headers = self.client(); identifier=uuid.uuid4(); url=f'/v1/submissions/{identifier}/decision'
        body={'decision':'approved','comment':'Checked source'}
        with patch('runreviq.submissions.decide',return_value={'status':'approved'}) as decide:
            self.assertEqual(client.post(url,json=body,headers=headers).status_code,403)
            decide.assert_not_called()
            self.write({'google':[],'demo':[records[0]['subject']]})
            self.assertEqual(client.post(url,json={**body,'reviewer':'other'},headers=headers).status_code,422)
            self.assertEqual(client.post(url,json=body,headers=headers).status_code,200)
            decide.assert_called_once_with(owner_key('demo',records[0]['subject']),identifier,'approved','Checked source')


@unittest.skipUnless(os.environ.get('RUNREVIQ_TEST_DATABASE')=='1','Requires disposable PostgreSQL')
class SubmissionDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dbname='opslens_test_'+uuid.uuid4().hex
        with connect(dbname='postgres',autocommit=True) as conn:
            conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(cls.dbname)))
        cls.addClassCleanup(cls.drop_database); bootstrap(cls.dbname)

    @classmethod
    def drop_database(cls):
        assert cls.dbname.startswith('opslens_test_')
        with connect(dbname='postgres',autocommit=True) as conn:
            conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(cls.dbname)))

    def setUp(self):
        self.owner=owner_key('demo',uuid.uuid4().hex); self.reviewer=owner_key('demo',uuid.uuid4().hex)
        self.draft=create_draft(self.owner,'example.md','# Original\n',dbname=self.dbname)

    def submit(self):
        save_review(self.owner,self.draft['id'],0,METADATA,dbname=self.dbname)
        return workflow.submit(self.owner,self.draft['id'],1,dbname=self.dbname)

    def test_submission_requires_valid_latest_owned_revision(self):
        with self.assertRaises(ReviewConflict): workflow.submit(self.owner,self.draft['id'],1,dbname=self.dbname)
        save_review(self.owner,self.draft['id'],0,{**METADATA,'service':''},dbname=self.dbname)
        with self.assertRaises(DraftInputError): workflow.submit(self.owner,self.draft['id'],1,dbname=self.dbname)
        save_review(self.owner,self.draft['id'],1,METADATA,dbname=self.dbname)
        with self.assertRaises(ReviewConflict): workflow.submit(self.owner,self.draft['id'],1,dbname=self.dbname)
        self.assertIsNone(workflow.submit(self.reviewer,self.draft['id'],2,dbname=self.dbname))
        self.assertIsNone(workflow.own_submissions(self.reviewer,self.draft['id'],dbname=self.dbname))

    def test_submitted_snapshot_survives_later_edits_and_retry(self):
        submitted=self.submit()
        self.assertEqual(workflow.submit(self.owner,self.draft['id'],1,dbname=self.dbname),submitted)
        save_review(self.owner,self.draft['id'],1,{**METADATA,'title':'Later'},dbname=self.dbname)
        detail=workflow.submission_detail(self.reviewer,submitted['id'],dbname=self.dbname)
        self.assertEqual(detail['review']['metadata']['title'],'Example')
        self.assertEqual(detail['content'],'# Original\n')
        self.assertEqual(detail['proposal']['proposed_metadata']['title'],'Original')

    def test_unsubmitted_drafts_and_revisions_are_not_visible_to_reviewer(self):
        with workflow.connect_reviewer(self.dbname) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM opslens.upload_drafts WHERE id=%s',(self.draft['id'],)).fetchone()[0],0)
        self.submit(); save_review(self.owner,self.draft['id'],1,{**METADATA,'title':'Unsubmitted'},dbname=self.dbname)
        with workflow.connect_reviewer(self.dbname) as conn:
            self.assertEqual(conn.execute('SELECT revision FROM opslens.draft_reviews WHERE draft_id=%s',(self.draft['id'],)).fetchall(),[(1,)])

    def test_independent_decision_and_owner_feedback_never_publish(self):
        submitted=self.submit()
        self.assertIsNone(workflow.submission_detail(self.owner,submitted['id'],dbname=self.dbname))
        self.assertIsNone(workflow.decide(self.owner,submitted['id'],'approved','Self',dbname=self.dbname))
        result=workflow.decide(self.reviewer,submitted['id'],'changes_requested','Clarify environment',dbname=self.dbname)
        self.assertFalse(result['published'])
        history=workflow.own_submissions(self.owner,self.draft['id'],dbname=self.dbname)
        self.assertEqual(history[0]['comment'],'Clarify environment')
        self.assertEqual(history[0]['status'],'changes_requested')
        self.assertEqual(load_authorized_documents('platform',dbname=self.dbname),[])
        with self.assertRaises(ReviewConflict): workflow.decide(self.reviewer,submitted['id'],'approved','Changed mind',dbname=self.dbname)

    def test_concurrent_decisions_cannot_overwrite(self):
        submitted=self.submit()
        def vote(actor):
            try: return workflow.decide(actor,submitted['id'],'approved','Checked',dbname=self.dbname)['status']
            except ReviewConflict: return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(vote,[self.reviewer,owner_key('demo','second-reviewer')]))
        self.assertCountEqual(results,['approved','conflict'])

    def test_database_grants_and_owner_policies(self):
        submitted=self.submit()
        with connect_drafts(self.dbname) as conn:
            scope(conn,self.reviewer)
            self.assertEqual(conn.execute('SELECT count(*) FROM opslens.draft_submissions WHERE id=%s',(submitted['id'],)).fetchone()[0],0)
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                conn.execute('INSERT INTO opslens.draft_submissions(id,draft_id,revision) VALUES (%s,%s,1)',(uuid.uuid4(),self.draft['id']))
        for statement in ('SELECT * FROM opslens.documents','DELETE FROM opslens.submission_decisions',"UPDATE opslens.draft_reviews SET metadata='{}'",'SET ROLE opslens_draft_writer'):
            with workflow.connect_reviewer(self.dbname) as conn, self.assertRaises(psycopg.errors.InsufficientPrivilege): conn.execute(statement)
        with workflow.connect_reviewer(self.dbname) as conn:
            conn.execute("SELECT set_config('opslens.reviewer',%s,true)",(self.owner,))
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                conn.execute("INSERT INTO opslens.submission_decisions VALUES (%s,%s,'approved','Self',now())",(submitted['id'],self.owner))
        with connect_drafts(self.dbname) as conn, self.assertRaises(psycopg.errors.InsufficientPrivilege):
            scope(conn,self.owner)
            conn.execute("INSERT INTO opslens.submission_decisions VALUES (%s,%s,'approved','Fake',now())",(submitted['id'],self.reviewer))

    def test_blank_comment_is_rejected(self):
        submitted=self.submit()
        with self.assertRaises(DraftInputError): workflow.decide(self.reviewer,submitted['id'],'approved','  ',dbname=self.dbname)
