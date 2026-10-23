"""Explicit publication of approved snapshots through a restricted backend account."""
import hashlib
import json
import re
import uuid

import psycopg
from psycopg.types.json import Jsonb

from runreviq.database import credentials
from runreviq.drafts import DraftInputError, ReviewConflict, validate_review
from runreviq.selector import ROOT, ROLES
from runreviq.submissions import can_review, initialize_reviewers

PUBLISHERS_FILE = ROOT / '.local/publishers.json'


def can_publish(mode, subject, path=PUBLISHERS_FILE):
    return can_review(mode, subject, path)


def connect_publisher(dbname='opslens'):
    password = credentials().get('PUBLISH_PASSWORD')
    if not password:
        raise ValueError('Publication storage is not configured')
    return psycopg.connect(host='127.0.0.1', port=55432, dbname=dbname,
                          user='opslens_publish_operator', password=password, connect_timeout=5)


def queue(*, dbname='opslens'):
    with connect_publisher(dbname) as conn:
        rows = conn.execute('''SELECT s.id,u.filename,s.revision FROM opslens.draft_submissions s
            JOIN opslens.upload_drafts u ON u.id=s.draft_id
            LEFT JOIN opslens.publications p ON p.submission_id=s.id
            WHERE p.submission_id IS NULL AND NOT EXISTS (
                SELECT 1 FROM opslens.publications newer JOIN opslens.draft_submissions ns ON ns.id=newer.submission_id
                WHERE ns.draft_id=s.draft_id AND ns.revision>=s.revision)
            ORDER BY s.created_at,s.id LIMIT 100''').fetchall()
    return [{'id':str(i),'filename':name,'revision':r} for i,name,r in rows]


def snapshot(conn, identifier):
    return conn.execute('''SELECT s.draft_id,s.revision,u.filename,u.content,r.metadata,d.comment
        FROM opslens.draft_submissions s JOIN opslens.upload_drafts u ON u.id=s.draft_id
        JOIN opslens.draft_reviews r ON r.draft_id=s.draft_id AND r.revision=s.revision
        JOIN opslens.submission_decisions d ON d.submission_id=s.id AND d.decision='approved'
        WHERE s.id=%s''', (identifier,)).fetchone()


def detail(identifier, *, dbname='opslens'):
    with connect_publisher(dbname) as conn:
        row = snapshot(conn, identifier)
    if row is None:
        return None
    draft,r,name,content,metadata,comment = row
    return {'id':str(identifier),'revision':r,'filename':name,'content':content,
            'metadata':metadata,'review_comment':comment}


def prepare_claims(claims, content):
    if not isinstance(claims,list) or not 1 <= len(claims) <= 20:
        raise DraftInputError('Supply 1–20 reviewed claims')
    lines = content.splitlines()
    digest = hashlib.sha256(content.encode()).hexdigest()
    result, seen = [], set()
    for claim in claims:
        if not isinstance(claim,dict) or set(claim) != {'action','rule','start_line','end_line'}:
            raise DraftInputError('Invalid claim fields')
        action,rule,start,end = (claim[k] for k in ('action','rule','start_line','end_line'))
        if (not isinstance(action,str) or not re.fullmatch(r'[a-z][a-z_]{0,99}',action)
                or rule not in ('must','must_not') or type(start) is not int or type(end) is not int
                or not 1 <= start <= end <= len(lines)):
            raise DraftInputError('Invalid claim or source range')
        quote = '\n'.join(lines[start-1:end])
        if not quote.strip() or action in seen:
            raise DraftInputError('Empty evidence or repeated action')
        seen.add(action)
        result.append({'action':action,'rule':rule,'citation':{'start_line':start,'end_line':end,
                      'quote':quote,'source_sha256':digest}})
    return result


def publish(actor, identifier, roles, claims, verified, *, dbname='opslens'):
    if (verified is not True or not isinstance(roles,list) or not roles
            or any(not isinstance(r,str) or r not in ROLES for r in roles) or len(set(roles)) != len(roles)):
        raise DraftInputError('Verify metadata and choose explicit reading roles')
    with connect_publisher(dbname) as conn:
        conn.execute("SELECT set_config('opslens.publisher',%s,true)",(actor,))
        # Share the catalog-ingestion lock: publication and fixture ingestion cannot interleave.
        conn.execute('SELECT pg_advisory_xact_lock(710422)')
        row = snapshot(conn,identifier)
        if row is None:
            return None
        draft,revision,name,content,raw,comment = row
        review = validate_review(raw)
        if review['issues']:
            raise DraftInputError('Invalid approved metadata')
        cited = prepare_claims(claims,content)
        document_id = 'UPLOAD-' + str(uuid.UUID(str(draft)).int)
        metadata = dict(review['validated_metadata'],id=document_id,revision=revision,
                        status='approved',metadata_verified=True,claims=cited,path='submission:'+str(identifier))
        checksum = hashlib.sha256(json.dumps({'metadata':metadata,'content':content},sort_keys=True).encode()).hexdigest()
        previous = conn.execute('''SELECT p.document_id,p.revision,p.allowed_roles,v.checksum,p.created_at FROM opslens.publications p
            JOIN opslens.document_versions v ON v.document_id=p.document_id AND v.revision=p.revision
            WHERE p.submission_id=%s''',(identifier,)).fetchone()
        if previous:
            if previous[2] != sorted(roles) or previous[3] != checksum:
                raise ReviewConflict()
            return {'document_id':previous[0],'revision':previous[1],'published':True,'published_at':previous[4].isoformat()}
        current = conn.execute('SELECT current_revision FROM opslens.documents WHERE id=%s',(document_id,)).fetchone()
        if current and current[0] >= revision:
            raise ReviewConflict()
        conn.execute('''INSERT INTO opslens.documents(id,current_revision,allowed_roles) VALUES (%s,%s,%s)
            ON CONFLICT(id) DO UPDATE SET current_revision=EXCLUDED.current_revision,allowed_roles=EXCLUDED.allowed_roles''',
                     (document_id,revision,sorted(roles)))
        conn.execute('INSERT INTO opslens.document_versions(document_id,revision,checksum,metadata,content) VALUES (%s,%s,%s,%s,%s)',
                     (document_id,revision,checksum,Jsonb(metadata),content))
        at = conn.execute('''INSERT INTO opslens.publications(submission_id,document_id,revision,publisher,allowed_roles)
            VALUES (%s,%s,%s,%s,%s) RETURNING created_at''',(identifier,document_id,revision,actor,sorted(roles))).fetchone()[0]
    return {'document_id':document_id,'revision':revision,'published':True,'published_at':at.isoformat()}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Initialize an empty private publisher allowlist')
    parser.add_argument('command',choices=['init-publishers'])
    parser.parse_args()
    try:
        initialize_reviewers(PUBLISHERS_FILE)
    except FileExistsError:
        raise SystemExit('Publisher configuration already exists; left unchanged.')
    print('Created private publisher configuration with no assignments.')
