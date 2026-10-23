"""Explicit submission and independent decisions; never publishes evidence."""
import json
import os
from pathlib import Path
import stat
import uuid

import psycopg

from runreviq.database import credentials
from runreviq.drafts import connect_drafts, scope, latest_review, validate_review, ReviewConflict, DraftInputError
from runreviq.selector import ROOT

REVIEWERS_FILE = ROOT / '.local/reviewers.json'


def can_review(mode, subject, path=REVIEWERS_FILE):
    """Reload an operator-owned allowlist; missing means no reviewers."""
    path = Path(path)
    if not path.exists():
        return False
    with path.open() as stream:
        if stat.S_IMODE(os.fstat(stream.fileno()).st_mode) & 0o077:
            raise ValueError('Reviewer configuration must be owner-only')
        data = json.load(stream)
    if (not isinstance(data, dict) or set(data) != {'google', 'demo'}
            or any(not isinstance(v, list) or any(not isinstance(s, str) or not s.strip() or len(s)>255 for s in v) for v in data.values())):
        raise ValueError('Invalid reviewer configuration')
    return subject in data[mode]


def connect_reviewer(dbname='opslens'):
    password = credentials().get('REVIEW_PASSWORD')
    if not password:
        raise ValueError('Review storage is not configured')
    return psycopg.connect(host='127.0.0.1', port=55432, dbname=dbname,
                          user='opslens_review_operator', password=password, connect_timeout=5)


def own_submissions(owner, draft_id, *, dbname='opslens'):
    with connect_drafts(dbname) as conn:
        scope(conn, owner)
        if not conn.execute('SELECT 1 FROM opslens.upload_drafts WHERE id=%s', (draft_id,)).fetchone():
            return None
        rows = conn.execute('''SELECT s.id,s.revision,s.created_at,d.decision,d.comment,d.created_at
            FROM opslens.draft_submissions s LEFT JOIN opslens.submission_decisions d ON d.submission_id=s.id
            WHERE s.draft_id=%s ORDER BY s.revision DESC''', (draft_id,)).fetchall()
    return [{'id':str(i),'revision':r,'submitted_at':at.isoformat(),'status':decision or 'pending',
             'comment':comment,'decided_at':when.isoformat() if when else None} for i,r,at,decision,comment,when in rows]


def submit(owner, draft_id, revision, *, dbname='opslens'):
    with connect_drafts(dbname) as conn:
        scope(conn, owner)
        conn.execute('SELECT pg_advisory_xact_lock(%s)', (int(uuid.UUID(str(draft_id)).hex[:15],16),))
        if not conn.execute('SELECT 1 FROM opslens.upload_drafts WHERE id=%s', (draft_id,)).fetchone():
            return None
        review = latest_review(conn, draft_id)
        if not review or review['revision'] != revision:
            raise ReviewConflict()
        if review['issues']:
            raise DraftInputError('Complete all metadata before submission')
        # Retrying a submission does not create duplicates or change its decision.
        row = conn.execute('SELECT id FROM opslens.draft_submissions WHERE draft_id=%s AND revision=%s', (draft_id,revision)).fetchone()
        identifier = row[0] if row else uuid.uuid4()
        if not row:
            conn.execute('INSERT INTO opslens.draft_submissions(id,draft_id,revision) VALUES (%s,%s,%s)', (identifier,draft_id,revision))
    return {'id':str(identifier),'revision':revision,'published':False}


def review_queue(reviewer, *, dbname='opslens'):
    with connect_reviewer(dbname) as conn:
        rows = conn.execute('''SELECT s.id,u.filename,s.revision,s.created_at
            FROM opslens.draft_submissions s JOIN opslens.upload_drafts u ON u.id=s.draft_id
            LEFT JOIN opslens.submission_decisions d ON d.submission_id=s.id
            WHERE d.submission_id IS NULL AND u.owner<>%s ORDER BY s.created_at,s.id LIMIT 100''', (reviewer,)).fetchall()
    return [{'id':str(i),'filename':name,'revision':r,'submitted_at':at.isoformat()} for i,name,r,at in rows]


def submission_detail(reviewer, identifier, *, dbname='opslens'):
    with connect_reviewer(dbname) as conn:
        row = conn.execute('''SELECT s.id,s.revision,u.filename,u.content,u.proposal,r.metadata,d.decision,d.comment
            FROM opslens.draft_submissions s JOIN opslens.upload_drafts u ON u.id=s.draft_id
            JOIN opslens.draft_reviews r ON r.draft_id=s.draft_id AND r.revision=s.revision
            LEFT JOIN opslens.submission_decisions d ON d.submission_id=s.id
            WHERE s.id=%s AND u.owner<>%s''', (identifier,reviewer)).fetchone()
    if not row:
        return None
    i,r,name,content,proposal,metadata,decision,comment = row
    return {'id':str(i),'revision':r,'filename':name,'content':content,'proposal':proposal,
            'review':validate_review(metadata),'status':decision or 'pending','comment':comment,'published':False}


def decide(reviewer, identifier, decision, comment, *, dbname='opslens'):
    if decision not in ('approved','changes_requested') or not isinstance(comment,str) or not comment.strip() or len(comment)>2000 or '\x00' in comment:
        raise DraftInputError('Decision and comment required')
    with connect_reviewer(dbname) as conn:
        conn.execute("SELECT set_config('opslens.reviewer', %s, true)", (reviewer,))
        # Separate namespace from draft locks; decisions are immutable and single-use.
        conn.execute('SELECT pg_advisory_xact_lock(%s)', (-int(uuid.UUID(str(identifier)).hex[:15],16)-1,))
        row = conn.execute('''SELECT r.metadata FROM opslens.draft_submissions s
            JOIN opslens.upload_drafts u ON u.id=s.draft_id
            JOIN opslens.draft_reviews r ON r.draft_id=s.draft_id AND r.revision=s.revision
            WHERE s.id=%s AND u.owner<>%s''', (identifier,reviewer)).fetchone()
        if not row:
            return None
        if conn.execute('SELECT 1 FROM opslens.submission_decisions WHERE submission_id=%s', (identifier,)).fetchone():
            raise ReviewConflict()
        if decision == 'approved' and validate_review(row[0])['issues']:
            raise DraftInputError('Cannot approve invalid metadata')
        at = conn.execute('''INSERT INTO opslens.submission_decisions(submission_id,reviewer,decision,comment)
            VALUES (%s,%s,%s,%s) RETURNING created_at''', (identifier,reviewer,decision,comment.strip())).fetchone()[0]
    return {'id':str(identifier),'status':decision,'comment':comment.strip(),'decided_at':at.isoformat(),'published':False}


def initialize_reviewers(path=REVIEWERS_FILE):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump({'google': [], 'demo': []}, stream, indent=2)
        stream.write('\n')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Initialize an empty private reviewer allowlist')
    parser.add_argument('command', choices=['init-reviewers'])
    parser.parse_args()
    try:
        initialize_reviewers()
    except FileExistsError:
        raise SystemExit('Reviewer configuration already exists; left unchanged.')
    print('Created private reviewer configuration with no reviewers assigned.')
