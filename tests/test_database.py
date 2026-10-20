"""Opt-in integration tests; all test writes use a fresh disposable database."""
import copy
import os
import unittest
import uuid

from opslens.selector import load_documents, select


@unittest.skipUnless(os.environ.get('OPSLENS_TEST_DATABASE') == '1', 'Set OPSLENS_TEST_DATABASE=1 for local DB integration tests')
class DatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from opslens.database import connect, bootstrap
        from psycopg import sql
        cls.dbname = 'opslens_test_' + uuid.uuid4().hex
        with connect(dbname='postgres', autocommit=True) as conn:
            conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(cls.dbname)))
        cls.addClassCleanup(cls.drop_database)
        bootstrap(cls.dbname)

    @classmethod
    def drop_database(cls):
        from opslens.database import connect
        from psycopg import sql
        assert cls.dbname.startswith('opslens_test_')
        with connect(dbname='postgres', autocommit=True) as conn:
            conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(cls.dbname)))

    def setUp(self):
        from opslens.database import connect, ingest
        # This database was created by this test class, never the development database.
        with connect(dbname=self.dbname) as conn:
            conn.execute('TRUNCATE opslens.document_versions, opslens.documents')
        self.docs = load_documents()
        ingest(self.docs, dbname=self.dbname)

    def test_file_database_parity(self):
        from opslens.database import load_authorized_documents
        for role in ('platform', 'security', 'intern'):
            for ver in ('2.1.0', '2.4.0', '2.5.0', '2.6.0'):
                for env in ('production', 'staging'):
                    for rotation in (True, False, None):
                        with self.subTest(role=role, version=ver, environment=env, rotation=rotation):
                            args = dict(role=role, service='identity-service', software_version=ver,
                                        environment=env, key_rotation_enabled=rotation)
                            self.assertEqual(select(self.docs, **args), select(load_authorized_documents(role, dbname=self.dbname), **args))

    def test_repeat_ingestion_is_noop(self):
        from opslens.database import ingest
        self.assertEqual(ingest(self.docs, dbname=self.dbname)['versions_inserted'], 0)

    def test_raw_reader_cannot_see_restricted_sources(self):
        from opslens.database import connect
        with connect(role='intern', dbname=self.dbname) as conn:
            ids = conn.execute('SELECT document_id FROM opslens.document_versions ORDER BY document_id').fetchall()
            self.assertEqual(ids, [('RB-044',)])
        with connect(role='platform', dbname=self.dbname) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM opslens.document_versions WHERE document_id IN ('SEC-021','RB-070')").fetchone()[0], 0)

    def test_reader_is_not_privileged(self):
        from opslens.database import connect
        with connect(role='platform', dbname=self.dbname) as conn:
            self.assertEqual(conn.execute('SELECT rolsuper, rolcreatedb, rolcreaterole, rolbypassrls FROM pg_roles WHERE rolname=current_user').fetchone(), (False, False, False, False))

    def test_reader_cannot_write_or_assume_other_persona(self):
        import psycopg
        from opslens.database import connect
        for statement in ("UPDATE opslens.documents SET allowed_roles=ARRAY['intern']", 'SET ROLE opslens_reader_security'):
            with self.subTest(statement=statement), self.assertRaises(psycopg.errors.InsufficientPrivilege):
                with connect(role='intern', dbname=self.dbname) as conn:
                    conn.execute(statement)

    def test_same_revision_changes_roll_back_whole_batch(self):
        from opslens.database import connect, ingest
        new = copy.deepcopy(self.docs[0])
        new['id'] = 'RB-999'
        changed = copy.deepcopy(self.docs[1])
        changed['title'] = 'Changed without a revision bump'
        with self.assertRaises(ValueError):
            ingest([new, changed], dbname=self.dbname)
        with connect(dbname=self.dbname) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM opslens.documents WHERE id='RB-999'").fetchone()[0], 0)

    def test_new_revision_preserves_history_and_stale_upload_cannot_replace_it(self):
        from opslens.database import connect, ingest
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
        from opslens.database import ingest, load_authorized_documents
        changed = copy.deepcopy(self.docs[1])
        changed['allowed_roles'] = ['security']
        self.assertEqual(ingest([changed], dbname=self.dbname)['versions_inserted'], 0)
        self.assertNotIn('RB-042', [d['id'] for d in load_authorized_documents('platform', dbname=self.dbname)])

    def test_database_rejects_in_place_revision_update(self):
        import psycopg
        from opslens.database import connect
        with self.assertRaises(psycopg.errors.RaiseException):
            with connect(dbname=self.dbname) as conn:
                conn.execute("UPDATE opslens.document_versions SET content='changed' WHERE document_id='RB-042'")

    def test_migration_is_repeatable(self):
        from opslens.database import bootstrap
        bootstrap(self.dbname)


class CatalogValidationTests(unittest.TestCase):
    def test_reject_invalid_catalog_before_ingestion(self):
        from opslens.database import prepare
        for updates in ({'path': '../../.env'}, {'revision': 0}, {'revision': True},
                        {'allowed_roles': ['admin']}, {'version_min': '2.5.0', 'version_max_exclusive': '2.4.0'},
                        {'key_rotation_enabled': 'true'}, {'metadata_verified': 'true'}):
            with self.subTest(updates=updates):
                doc = copy.deepcopy(load_documents()[0])
                doc.update(updates)
                with self.assertRaises(ValueError):
                    prepare([doc])

    def test_duplicate_ids_rejected(self):
        from opslens.database import prepare
        doc = load_documents()[0]
        with self.assertRaises(ValueError):
            prepare([doc, doc])
