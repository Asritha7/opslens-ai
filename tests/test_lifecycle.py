import copy
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

from runreviq import lifecycle
from runreviq.api import create_app,initialize_keys,read_keys
from runreviq.database import connect,bootstrap,ingest,load_authorized_documents,load_authorized_revision
from runreviq.drafts import owner_key,ReviewConflict,DraftInputError
from runreviq.publications import connect_publisher
from runreviq.selector import load_documents


class LifecycleApiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name);keys=root/'keys.json';initialize_keys(keys)
        self.record=read_keys(keys)[0];self.allow=root/'publishers.json'
        self.client=TestClient(create_app(key_file=keys,oidc_file=None,publishers_file=self.allow));self.addCleanup(self.client.close)
        self.headers={'Authorization':'Bearer '+self.record['token']}
        self.base='/v1/publication-management/documents'

    def grant(self):
        self.allow.write_text(json.dumps({'google':[],'demo':[self.record['subject']]}));self.allow.chmod(0o600)

    def test_management_requires_publisher_on_every_route(self):
        for path in (self.base,self.base+'/RB-001',self.base+'/RB-001/revisions/1'):
            self.assertEqual(self.client.get(path).status_code,401)
            self.assertEqual(self.client.get(path,headers=self.headers).status_code,403)
        with patch('runreviq.lifecycle.withdraw') as call:
            self.assertEqual(self.client.post(self.base+'/RB-001/withdraw',headers=self.headers,json={'expected_revision':1,'reason':'Unsafe'}).status_code,403)
            call.assert_not_called()

    def test_actor_is_server_derived_and_revocation_is_immediate(self):
        self.grant();body={'expected_revision':1,'reason':'Outdated'}
        with patch('runreviq.lifecycle.withdraw',return_value={'status':'withdrawn'}) as call:
            response=self.client.post(self.base+'/RB-001/withdraw',headers=self.headers,json=body)
            self.assertEqual(response.status_code,200)
            call.assert_called_once_with(owner_key('demo',self.record['subject']),'RB-001',1,'Outdated')
            self.assertEqual(self.client.post(self.base+'/RB-001/withdraw',headers=self.headers,json={**body,'actor':'forged'}).status_code,422)
            self.allow.unlink()
            self.assertEqual(self.client.post(self.base+'/RB-001/withdraw',headers=self.headers,json=body).status_code,403)

    def test_conflict_failure_and_missing_are_explicit(self):
        self.grant()
        for error,code in [(ReviewConflict(),409),(DraftInputError('private'),422),(psycopg.OperationalError('private'),503)]:
            with patch('runreviq.lifecycle.withdraw',side_effect=error):
                r=self.client.post(self.base+'/RB-001/withdraw',headers=self.headers,json={'expected_revision':1,'reason':'Outdated'})
                self.assertEqual(r.status_code,code);self.assertNotIn('private',r.text)
        with patch('runreviq.lifecycle.history',return_value=None):
            self.assertEqual(self.client.get(self.base+'/RB-001',headers=self.headers).status_code,404)


@unittest.skipUnless(os.environ.get('RUNREVIQ_TEST_DATABASE')=='1','Requires disposable PostgreSQL')
class LifecycleDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dbname='opslens_test_'+uuid.uuid4().hex
        with connect(dbname='postgres',autocommit=True) as conn:
            conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(cls.dbname)))
        cls.addClassCleanup(cls.drop_database);bootstrap(cls.dbname)

    @classmethod
    def drop_database(cls):
        assert cls.dbname.startswith('opslens_test_')
        with connect(dbname='postgres',autocommit=True) as conn:
            conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(cls.dbname)))

    def setUp(self):
        with connect(dbname=self.dbname) as c:
            c.execute('TRUNCATE opslens.document_withdrawals,opslens.publications,opslens.document_versions,opslens.documents')
        self.docs=load_documents()
        self.doc=next(d for d in self.docs if d['status']=='approved' and 'platform' in d['allowed_roles'])
        self.doc['allowed_roles']=['platform']
        ingest(self.docs,dbname=self.dbname)
        self.id=self.doc['id'];self.rev=self.doc['revision'];self.actor=owner_key('demo','publisher')

    def withdraw(self,reason='Outdated instruction',revision=None,actor=None):
        return lifecycle.withdraw(actor or self.actor,self.id,revision or self.rev,reason,dbname=self.dbname)

    def test_withdrawal_excludes_guidance_preserves_exact_history(self):
        before=load_authorized_revision('platform',self.id,self.rev,dbname=self.dbname)
        self.assertIn(self.id,[d['id'] for d in load_authorized_documents('platform',dbname=self.dbname)])
        receipt=self.withdraw()
        self.assertNotIn(self.id,[d['id'] for d in load_authorized_documents('platform',dbname=self.dbname)])
        after=load_authorized_revision('platform',self.id,self.rev,dbname=self.dbname)
        for key in ('content','checksum','revision_status'):self.assertEqual(before[key],after[key])
        self.assertEqual(after['guidance_status'],'withdrawn');self.assertEqual(after['withdrawal']['reason'],receipt['reason'])
        self.assertIsNone(load_authorized_revision('intern',self.id,self.rev,dbname=self.dbname))
        history=lifecycle.history(self.id,dbname=self.dbname)
        self.assertEqual(history['revisions'][0]['withdrawal']['actor'],self.actor)
        self.assertEqual(history['allowed_roles'],['platform'])

    def test_idempotent_retry_cannot_rewrite_reason_or_actor(self):
        first=self.withdraw();self.assertEqual(first,self.withdraw())
        for kwargs in ({'reason':'different'},{'actor':owner_key('demo','other')}):
            with self.assertRaises(ReviewConflict):self.withdraw(**kwargs)

    def test_invalid_reason_and_stale_revision_do_not_withdraw(self):
        for reason in ('','  ','x'*2001,'a\x00b'):
            with self.assertRaises(DraftInputError):self.withdraw(reason)
        with self.assertRaises(ReviewConflict):self.withdraw(revision=self.rev+1)
        self.assertIn(self.id,[d['id'] for d in load_authorized_documents('platform',dbname=self.dbname)])

    def test_reingestion_does_not_restore_withdrawn_revision(self):
        self.withdraw();ingest(self.docs,dbname=self.dbname)
        self.assertNotIn(self.id,[d['id'] for d in load_authorized_documents('platform',dbname=self.dbname)])
        self.assertEqual(lifecycle.documents(dbname=self.dbname)['documents'][[d['document_id'] for d in lifecycle.documents(dbname=self.dbname)['documents']].index(self.id)]['status'],'withdrawn')

    def test_new_revision_is_active_and_withdrawn_history_is_retained(self):
        self.withdraw();new=copy.deepcopy(self.doc);new['revision']+=1
        ingest([new],dbname=self.dbname)
        h=lifecycle.history(self.id,dbname=self.dbname)
        self.assertEqual(h['revisions'][0]['status'],'active')
        self.assertEqual(h['revisions'][1]['status'],'withdrawn')
        self.assertEqual(h['revisions'][1]['superseded_by'],new['revision'])
        self.assertIn(self.id,[d['id'] for d in load_authorized_documents('platform',dbname=self.dbname)])
        with self.assertRaises(ReviewConflict):self.withdraw()

    def test_superseded_status_without_withdrawal(self):
        new=copy.deepcopy(self.doc);new['revision']+=1;ingest([new],dbname=self.dbname)
        old=lifecycle.revision(self.id,self.rev,dbname=self.dbname)
        self.assertEqual(old['status'],'superseded')
        self.assertEqual(load_authorized_revision('platform',self.id,self.rev,dbname=self.dbname)['guidance_status'],'superseded')

    def test_concurrent_withdrawals_do_not_overwrite(self):
        def act(reason):
            try:self.withdraw(reason);return 'saved'
            except ReviewConflict:return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:result=list(pool.map(act,['First reason','Second reason']))
        self.assertCountEqual(result,['saved','conflict'])

    def test_rls_and_append_only_grants(self):
        self.withdraw()
        with connect(role='intern',dbname=self.dbname) as c:
            self.assertEqual(c.execute('SELECT reason FROM opslens.document_withdrawals').fetchall(),[])
        with connect(role='platform',dbname=self.dbname) as c:
            self.assertEqual(len(c.execute('SELECT reason FROM opslens.document_withdrawals').fetchall()),1)
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):c.execute('SELECT actor FROM opslens.document_withdrawals')
        for cmd in ('DELETE FROM opslens.document_withdrawals',"UPDATE opslens.document_withdrawals SET reason='changed'"):
            with connect_publisher(self.dbname) as c,self.assertRaises(psycopg.errors.InsufficientPrivilege):c.execute(cmd)

    def test_document_pagination_has_no_duplicates_or_omissions(self):
        extra=[]
        for n in range(60):
            doc=copy.deepcopy(self.doc);doc['id']='PAGE-'+str(n);extra.append(doc)
        ingest(extra,dbname=self.dbname)
        first=lifecycle.documents(dbname=self.dbname);second=lifecycle.documents(first['next_after'],dbname=self.dbname)
        ids=[d['document_id'] for d in first['documents']+second['documents']]
        self.assertEqual(len(ids),len(set(ids)));self.assertEqual(len(ids),len(self.docs)+60);self.assertIsNone(second['next_after'])
