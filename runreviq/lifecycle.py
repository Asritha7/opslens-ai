"""Publisher-managed withdrawal and inspection of immutable published history."""
import re

from runreviq.drafts import DraftInputError, ReviewConflict
from runreviq.publications import connect_publisher


def validate_id(identifier):
    if not isinstance(identifier,str) or not re.fullmatch(r'[A-Z]+-[0-9]+',identifier) or len(identifier)>100:
        raise DraftInputError('Invalid document ID')


def status(recorded, revision, current, withdrawn):
    if withdrawn:
        return 'withdrawn'
    if revision != current:
        return 'superseded'
    return 'active' if recorded == 'approved' else recorded


def documents(after='', *, dbname='opslens'):
    if after:
        validate_id(after)
    with connect_publisher(dbname) as conn:
        rows = conn.execute('''SELECT d.id,d.current_revision,d.allowed_roles,v.metadata,v.created_at,w.reason,w.created_at
            FROM opslens.documents d JOIN opslens.document_versions v ON v.document_id=d.id AND v.revision=d.current_revision
            LEFT JOIN opslens.document_withdrawals w ON w.document_id=d.id AND w.revision=d.current_revision
            WHERE d.id>%s ORDER BY d.id LIMIT 51''',(after,)).fetchall()
    items = [{'document_id':i,'current_revision':r,'allowed_roles':roles,'title':m['title'],
              'status':status(m['status'],r,r,reason is not None),'published_at':at.isoformat(),
              'withdrawal':{'reason':reason,'withdrawn_at':when.isoformat()} if reason is not None else None}
             for i,r,roles,m,at,reason,when in rows[:50]]
    return {'documents':items,'next_after':items[-1]['document_id'] if len(rows)>50 else None}


def history(identifier, *, dbname='opslens'):
    validate_id(identifier)
    with connect_publisher(dbname) as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        doc = conn.execute('SELECT current_revision,allowed_roles FROM opslens.documents WHERE id=%s',(identifier,)).fetchone()
        if not doc:
            return None
        rows = conn.execute('''SELECT v.revision,v.metadata,v.created_at,w.reason,w.created_at,w.actor
            FROM opslens.document_versions v LEFT JOIN opslens.document_withdrawals w
            ON w.document_id=v.document_id AND w.revision=v.revision
            WHERE v.document_id=%s ORDER BY v.revision DESC''',(identifier,)).fetchall()
    current,roles = doc
    return {'document_id':identifier,'current_revision':current,'allowed_roles':roles,'revisions':[
        {'revision':r,'title':m['title'],'recorded_status':m['status'],
         'status':status(m['status'],r,current,reason is not None),'is_current':r==current,
         'superseded_by':current if r!=current else None,'published_at':at.isoformat(),
         'withdrawal':{'reason':reason,'withdrawn_at':when.isoformat(),'actor':actor} if reason is not None else None}
        for r,m,at,reason,when,actor in rows]}


def revision(identifier, number, *, dbname='opslens'):
    validate_id(identifier)
    if type(number) is not int or not 1<=number<=2147483647:
        raise DraftInputError('Invalid revision')
    with connect_publisher(dbname) as conn:
        row = conn.execute('''SELECT v.metadata,v.content,v.checksum,d.current_revision,w.reason,w.created_at
            FROM opslens.document_versions v JOIN opslens.documents d ON d.id=v.document_id
            LEFT JOIN opslens.document_withdrawals w ON w.document_id=v.document_id AND w.revision=v.revision
            WHERE v.document_id=%s AND v.revision=%s''',(identifier,number)).fetchone()
    if not row:
        return None
    metadata,content,checksum,current,reason,when = row
    return {'document_id':identifier,'revision':number,'metadata':metadata,'content':content,'checksum':checksum,
            'current_revision':current,'status':status(metadata['status'],number,current,reason is not None),
            'withdrawal':{'reason':reason,'withdrawn_at':when.isoformat()} if reason is not None else None}


def withdraw(actor, identifier, expected_revision, reason, *, dbname='opslens'):
    validate_id(identifier)
    if (type(expected_revision) is not int or not 1<=expected_revision<=2147483647
            or not isinstance(reason,str) or not reason.strip() or len(reason)>2000 or '\x00' in reason):
        raise DraftInputError('A nonempty withdrawal reason and current revision are required')
    reason = reason.strip()
    with connect_publisher(dbname) as conn:
        conn.execute('SELECT pg_advisory_xact_lock(710422)')
        conn.execute("SELECT set_config('opslens.publisher',%s,true)",(actor,))
        row = conn.execute('''SELECT d.current_revision,v.metadata FROM opslens.documents d
            JOIN opslens.document_versions v ON v.document_id=d.id AND v.revision=d.current_revision
            WHERE d.id=%s''',(identifier,)).fetchone()
        if not row:
            return None
        if row[0] != expected_revision:
            raise ReviewConflict()
        if row[1]['status'] != 'approved':
            raise DraftInputError('Only approved current guidance can be withdrawn')
        previous = conn.execute('''SELECT actor,reason,created_at FROM opslens.document_withdrawals
            WHERE document_id=%s AND revision=%s''',(identifier,expected_revision)).fetchone()
        if previous:
            if previous[0]!=actor or previous[1]!=reason:
                raise ReviewConflict()
            at = previous[2]
        else:
            at = conn.execute('''INSERT INTO opslens.document_withdrawals(document_id,revision,actor,reason)
                VALUES (%s,%s,%s,%s) RETURNING created_at''',(identifier,expected_revision,actor,reason)).fetchone()[0]
    return {'document_id':identifier,'revision':expected_revision,'status':'withdrawn','reason':reason,'withdrawn_at':at.isoformat()}
