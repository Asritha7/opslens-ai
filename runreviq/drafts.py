"""Private, unpublished Markdown drafts; never a source for evidence selection."""
import hashlib
import re
import uuid

import psycopg
from psycopg.types.json import Jsonb

from runreviq.database import credentials
from runreviq.extraction import extract

MAX_BYTES = 1_000_000
MAX_DRAFTS = 20


class DraftInputError(ValueError):
    pass


class DraftLimit(Exception):
    pass


def prepare_draft(filename, content):
    # Filename is a display label, never a path. Uploaded bytes must be UTF-8.
    if not isinstance(filename, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 ._-]{0,116}\.md', filename, re.IGNORECASE):
        raise DraftInputError('Expected a simple Markdown filename')
    if not isinstance(content, str) or not content.strip() or '\x00' in content:
        raise DraftInputError('Expected nonempty Markdown text')
    encoded = content.encode('utf-8')
    if len(encoded) > MAX_BYTES:
        raise DraftInputError('Document exceeds 1 MB')
    return extract(content)


def owner_key(mode, subject):
    # Keep demo and Google identities separate without storing raw subjects in drafts.
    return hashlib.sha256((mode + ':' + subject).encode()).hexdigest()


def connect_drafts(dbname='opslens'):
    password = credentials().get('DRAFTS_PASSWORD')
    if not password:
        raise ValueError('Draft storage is not configured')
    return psycopg.connect(host='127.0.0.1', port=55432, dbname=dbname,
                          user='opslens_draft_writer', password=password, connect_timeout=5)


def scope(conn, owner):
    conn.execute("SELECT set_config('opslens.draft_owner', %s, true)", (owner,))


def create_draft(owner, filename, content, *, dbname='opslens'):
    proposal = prepare_draft(filename, content)
    identifier = uuid.uuid4()
    with connect_drafts(dbname) as conn:
        scope(conn, owner)
        # Serializes per-owner quota checks without granting reads of other owners.
        conn.execute('SELECT pg_advisory_xact_lock(%s)', (int(owner[:15], 16),))
        count = conn.execute('SELECT count(*) FROM opslens.upload_drafts').fetchone()[0]
        if count >= MAX_DRAFTS:
            raise DraftLimit()
        created = conn.execute('INSERT INTO opslens.upload_drafts(id, owner, filename, content, proposal) VALUES (%s,%s,%s,%s,%s) RETURNING created_at',
                               (identifier, owner, filename, content, Jsonb(proposal))).fetchone()[0]
    return {'id': str(identifier), 'filename': filename, 'created_at': created.isoformat(),
            'status': 'draft', 'content': content, 'proposal': proposal}


def list_drafts(owner, *, dbname='opslens'):
    with connect_drafts(dbname) as conn:
        scope(conn, owner)
        rows = conn.execute('SELECT id, filename, created_at FROM opslens.upload_drafts ORDER BY created_at DESC, id LIMIT %s', (MAX_DRAFTS,)).fetchall()
    return [{'id': str(id), 'filename': name, 'created_at': created.isoformat(), 'status': 'draft'} for id, name, created in rows]


def get_draft(owner, identifier, *, dbname='opslens'):
    with connect_drafts(dbname) as conn:
        scope(conn, owner)
        row = conn.execute('SELECT id, filename, created_at, content, proposal FROM opslens.upload_drafts WHERE id=%s', (identifier,)).fetchone()
    if row is None:
        return None
    id, filename, created, content, proposal = row
    return {'id': str(id), 'filename': filename, 'created_at': created.isoformat(),
            'status': 'draft', 'content': content, 'proposal': proposal}
