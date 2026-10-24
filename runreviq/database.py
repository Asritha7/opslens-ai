"""Local PostgreSQL bootstrap, transactional ingestion, and role-scoped reads."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from runreviq.citations import validate_citations
from runreviq.selector import ROOT, ROLES, load_documents, version


def credentials():
    # Intentionally limited format: literal KEY=value lines, no shell execution.
    values = {}
    path = ROOT / '.env'
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip() and not line.lstrip().startswith('#'):
                key, separator, value = line.partition('=')
                if not separator:
                    raise ValueError('Invalid .env line; expected KEY=value')
                values[key.strip()] = value.strip()
    for key in ['POSTGRES_PASSWORD', 'DRAFTS_PASSWORD', 'REVIEW_PASSWORD', 'PUBLISH_PASSWORD'] + [f'READER_{r.upper()}_PASSWORD' for r in ROLES]:
        if key in os.environ:
            values[key] = os.environ[key]
    return values


def connect(*, role=None, dbname='opslens', autocommit=False):
    if role is not None and role not in ROLES:
        raise ValueError('Unknown reader role')
    key = 'POSTGRES_PASSWORD' if role is None else f'READER_{role.upper()}_PASSWORD'
    password = credentials().get(key)
    if not password:
        raise ValueError(f'Missing {key}; see SETUP.md')
    return psycopg.connect(host='127.0.0.1', port=55432, dbname=dbname,
                          user='opslens_admin' if role is None else f'opslens_reader_{role}',
                          password=password, connect_timeout=5, autocommit=autocommit)


def bootstrap(dbname='opslens'):
    secrets = credentials()
    with connect(dbname=dbname) as conn:
        conn.execute('SELECT pg_advisory_xact_lock(710421)')
        for role in sorted(ROLES):
            name = f'opslens_reader_{role}'
            password = secrets.get(f'READER_{role.upper()}_PASSWORD')
            if not password:
                raise ValueError(f'Missing reader password for {role}')
            existing = conn.execute('SELECT rolsuper, rolcreaterole, rolcreatedb, rolbypassrls FROM pg_roles WHERE rolname=%s', (name,)).fetchone()
            if existing is None:
                conn.execute(sql.SQL('CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS PASSWORD {}').format(sql.Identifier(name), sql.Literal(password)))
            elif any(existing):
                raise ValueError(f'Refusing privileged existing reader role: {name}')
            if conn.execute('SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member WHERE r.rolname=%s', (name,)).fetchone():
                raise ValueError(f'Refusing reader role with inherited memberships: {name}')
        password = secrets.get('DRAFTS_PASSWORD')
        if not password:
            raise ValueError('Missing DRAFTS_PASSWORD; see SETUP.md')
        existing = conn.execute("SELECT rolsuper, rolcreaterole, rolcreatedb, rolbypassrls FROM pg_roles WHERE rolname='opslens_draft_writer'").fetchone()
        if existing is None:
            conn.execute(sql.SQL('CREATE ROLE opslens_draft_writer LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS PASSWORD {}').format(sql.Literal(password)))
        elif any(existing):
            raise ValueError('Refusing privileged draft writer')
        if conn.execute("SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member WHERE r.rolname='opslens_draft_writer'").fetchone():
            raise ValueError('Refusing draft writer with inherited memberships')
        password = secrets.get('REVIEW_PASSWORD')
        if not password:
            raise ValueError('Missing REVIEW_PASSWORD; see SETUP.md')
        existing = conn.execute("SELECT rolsuper, rolcreaterole, rolcreatedb, rolbypassrls FROM pg_roles WHERE rolname='opslens_review_operator'").fetchone()
        if existing is None:
            conn.execute(sql.SQL('CREATE ROLE opslens_review_operator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS PASSWORD {}').format(sql.Literal(password)))
        elif any(existing):
            raise ValueError('Refusing privileged review operator')
        if conn.execute("SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member WHERE r.rolname='opslens_review_operator'").fetchone():
            raise ValueError('Refusing review operator with memberships')
        password = secrets.get('PUBLISH_PASSWORD')
        if not password:
            raise ValueError('Missing PUBLISH_PASSWORD; see SETUP.md')
        existing = conn.execute("SELECT rolsuper, rolcreaterole, rolcreatedb, rolbypassrls FROM pg_roles WHERE rolname='opslens_publish_operator'").fetchone()
        if existing is None:
            conn.execute(sql.SQL('CREATE ROLE opslens_publish_operator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS PASSWORD {}').format(sql.Literal(password)))
        elif any(existing):
            raise ValueError('Refusing privileged publish operator')
        if conn.execute("SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member WHERE r.rolname='opslens_publish_operator'").fetchone():
            raise ValueError('Refusing publish operator with memberships')
        conn.execute('CREATE TABLE IF NOT EXISTS public.opslens_migrations (version text PRIMARY KEY, checksum text NOT NULL)')
        for path in sorted((ROOT / 'database/migrations').glob('[0-9][0-9][0-9]_*.sql')):
            version_id = path.name.split('_', 1)[0]
            migration = path.read_text()
            checksum = hashlib.sha256(migration.encode()).hexdigest()
            applied = conn.execute('SELECT checksum FROM public.opslens_migrations WHERE version=%s', (version_id,)).fetchone()
            if applied:
                if applied[0] != checksum:
                    raise ValueError('Applied migration was changed; create a new migration')
                continue
            conn.execute(migration)
            conn.execute('INSERT INTO public.opslens_migrations VALUES (%s, %s)', (version_id, checksum))


def prepare(documents, root=ROOT):
    """Validate the whole local batch before opening a write transaction."""
    records, seen = [], set()
    expected = {'id', 'title', 'revision', 'service', 'environment', 'version_min',
                'version_max_exclusive', 'key_rotation_enabled', 'allowed_roles',
                'metadata_verified', 'status', 'claims', 'path'}
    root = Path(root).resolve()
    for doc in documents:
        if set(doc) != expected:
            raise ValueError('Unexpected or missing catalog fields')
        if not re.fullmatch(r'[A-Z]+-[0-9]+', doc['id']):
            raise ValueError('Invalid document ID')
        if doc['id'] in seen:
            raise ValueError('Duplicate document ID in batch')
        seen.add(doc['id'])
        if type(doc['revision']) is not int or doc['revision'] < 1:
            raise ValueError('Revision must be a positive integer')
        if not all(isinstance(doc[k], str) and doc[k].strip() for k in ('title', 'service', 'path')):
            raise ValueError('Title, service and path must be non-empty strings')
        if doc['environment'] not in (None, 'production', 'staging'):
            raise ValueError('Invalid environment')
        if doc['status'] not in ('approved', 'draft', 'revoked', 'superseded'):
            raise ValueError('Invalid document status')
        if type(doc['metadata_verified']) is not bool:
            raise ValueError('metadata_verified must be boolean')
        if doc['key_rotation_enabled'] is not None and type(doc['key_rotation_enabled']) is not bool:
            raise ValueError('Invalid key rotation precondition')
        if not isinstance(doc['allowed_roles'], list) or any(r not in ROLES for r in doc['allowed_roles']):
            raise ValueError('Invalid allowed roles')
        for field in ('version_min', 'version_max_exclusive'):
            if doc[field] is not None:
                version(doc[field])
        if doc['version_min'] and doc['version_max_exclusive'] and version(doc['version_min']) >= version(doc['version_max_exclusive']):
            raise ValueError('Empty or inverted version range')
        if not isinstance(doc['claims'], list):
            raise ValueError('Claims must be a list')
        for claim in doc['claims']:
            if (not isinstance(claim, dict) or set(claim) not in ({'action', 'rule'}, {'action', 'rule', 'citation'}) or claim['rule'] not in ('must', 'must_not')
                    or not isinstance(claim['action'], str) or not re.fullmatch(r'[a-z_]+', claim['action'])):
                raise ValueError('Invalid normalized claim')
        path = (root / doc['path']).resolve()
        if not path.is_relative_to(root / 'datasets/northstar') or path.suffix != '.md':
            raise ValueError('Source must be Markdown inside datasets/northstar')
        if path.stat().st_size > 1_000_000:
            raise ValueError('Document exceeds 1 MB limit')
        content = path.read_text(encoding='utf-8')
        validate_citations(doc['claims'], content)
        # Permissions are current policy, not immutable historical evidence.
        metadata = {k: v for k, v in doc.items() if k != 'allowed_roles'}
        checksum = hashlib.sha256(json.dumps({'metadata': metadata, 'content': content}, sort_keys=True).encode()).hexdigest()
        records.append((doc, metadata, content, checksum))
    return records


def ingest(documents, *, dbname='opslens', root=ROOT):
    records = prepare(documents, root)
    inserted = 0
    with connect(dbname=dbname) as conn:
        # Small local corpus: serialize complete ingestion batches for predictable publication.
        conn.execute('SELECT pg_advisory_xact_lock(710422)')
        for doc, metadata, content, checksum in records:
            old = conn.execute('SELECT checksum FROM opslens.document_versions WHERE document_id=%s AND revision=%s', (doc['id'], doc['revision'])).fetchone()
            if old and old[0] != checksum:
                raise ValueError(f"{doc['id']} revision {doc['revision']} changed; increment revision")
            conn.execute('''INSERT INTO opslens.documents (id,current_revision,allowed_roles) VALUES (%s,%s,%s)
                            ON CONFLICT (id) DO UPDATE SET current_revision=EXCLUDED.current_revision,
                            allowed_roles=EXCLUDED.allowed_roles
                            WHERE opslens.documents.current_revision <= EXCLUDED.current_revision''',
                         (doc['id'], doc['revision'], [] if doc['status'] == 'revoked' else doc['allowed_roles']))
            if not old:
                conn.execute('INSERT INTO opslens.document_versions (document_id,revision,checksum,metadata,content) VALUES (%s,%s,%s,%s,%s)',
                             (doc['id'], doc['revision'], checksum, Jsonb(metadata), content))
                inserted += 1
    return {'documents_processed': len(records), 'versions_inserted': inserted}


def load_authorized_documents(role, *, dbname='opslens'):
    if role not in ROLES:
        raise ValueError('Unknown reader role')
    with connect(role=role, dbname=dbname) as conn:
        rows = conn.execute('''SELECT v.metadata, d.allowed_roles, v.content FROM opslens.documents d
                               JOIN opslens.document_versions v ON v.document_id=d.id AND v.revision=d.current_revision
                               WHERE NOT EXISTS (SELECT 1 FROM opslens.document_withdrawals w
                                   WHERE w.document_id=d.id AND w.revision=d.current_revision)
                               ORDER BY d.id''').fetchall()
    documents = []
    for metadata, roles, content in rows:
        validate_citations(metadata['claims'], content)
        documents.append(dict(metadata, allowed_roles=roles))
    return documents



def load_authorized_revision(role, document_id, revision, *, dbname='opslens'):
    """Read stored evidence through current RLS policy, including historical versions."""
    if role not in ROLES:
        raise ValueError('Unknown reader role')
    if not isinstance(document_id, str) or not re.fullmatch(r'[A-Z]+-[0-9]+', document_id):
        raise ValueError('Invalid document ID')
    if type(revision) is not int or not 1 <= revision <= 2147483647:
        raise ValueError('Invalid revision')
    with connect(role=role, dbname=dbname) as conn:
        row = conn.execute("""SELECT v.metadata, v.content, v.checksum, d.current_revision, w.reason, w.created_at
                              FROM opslens.document_versions v
                              JOIN opslens.documents d ON d.id=v.document_id
                              LEFT JOIN opslens.document_withdrawals w ON w.document_id=v.document_id AND w.revision=v.revision
                              WHERE v.document_id=%s AND v.revision=%s""",
                           (document_id, revision)).fetchone()
    if row is None:
        return None
    metadata, content, checksum, current_revision, reason, withdrawn_at = row
    return {'document_id': document_id, 'revision': revision,
            'title': metadata['title'], 'content': content, 'checksum': checksum,
            'current_revision': current_revision, 'is_current': revision == current_revision,
            'revision_status': metadata['status'],
            'guidance_status': 'withdrawn' if reason is not None else 'superseded' if revision != current_revision else 'active' if metadata['status']=='approved' else metadata['status'],
            'withdrawal': {'reason':reason,'withdrawn_at':withdrawn_at.isoformat()} if reason is not None else None}


def main():
    parser = argparse.ArgumentParser(description='Manage the local Runreviq database')
    parser.add_argument('command', choices=['bootstrap', 'ingest'])
    args = parser.parse_args()
    try:
        if args.command == 'bootstrap':
            bootstrap()
            print('Database migration and restricted reader accounts ready.')
        else:
            print(json.dumps(ingest(load_documents()), indent=2))
    except (ValueError, OSError, psycopg.Error):
        # Database exception details can include source rows. Do not print them in a user-facing CLI.
        parser.exit(1, 'Database operation failed; check local setup, catalog validity, and revision consistency. No partial ingestion batch was committed.\n')


if __name__ == '__main__':
    main()
