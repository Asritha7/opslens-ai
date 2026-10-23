"""Loopback API. Demo keys or Google sessions bind identities to reader roles."""
import argparse
import hashlib
import json
import os
import secrets
import stat
from uuid import UUID
from pathlib import Path
from typing import Literal

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Request, Path as ApiPath
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from runreviq.database import load_authorized_documents, load_authorized_revision
from runreviq import submissions
from runreviq.selector import ROOT, ROLES, select
from runreviq.oidc import GoogleSessions, install_routes
from runreviq.drafts import create_draft, list_drafts, get_draft, owner_key, DraftLimit, DraftInputError, MAX_BYTES, save_review, ReviewConflict

KEY_FILE = ROOT / '.local/api-keys.json'
OIDC_FILE = ROOT / '.local/google-oidc.json'


def initialize_keys(path=KEY_FILE):
    """Create local demo credentials without printing or overwriting existing keys."""
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    records = [{'subject': f'demo-{role}', 'role': role, 'token': secrets.token_urlsafe(32)}
               for role in sorted(ROLES)]
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(records, stream, indent=2)
        stream.write('\n')


def read_keys(path):
    """Reload on each request so removing a key revokes it without a restart."""
    with Path(path).open() as stream:
        if stat.S_IMODE(os.fstat(stream.fileno()).st_mode) & 0o077:
            raise ValueError('Credential file must be owner-only')
        records = json.load(stream)
    if not isinstance(records, list) or not records:
        raise ValueError('Invalid credential configuration')
    tokens, subjects = set(), set()
    for record in records:
        if (not isinstance(record, dict) or set(record) != {'subject', 'role', 'token'}
                or not isinstance(record['role'], str) or record['role'] not in ROLES
                or not isinstance(record['subject'], str) or not record['subject'].strip()
                or not isinstance(record['token'], str) or len(record['token']) < 32):
            raise ValueError('Invalid credential configuration')
        if record['token'] in tokens or record['subject'] in subjects:
            raise ValueError('Duplicate credential identity')
        tokens.add(record['token'])
        subjects.add(record['subject'])
    return records


class SelectionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    service: str = Field(min_length=1, max_length=100, pattern=r'^[a-zA-Z0-9_-]+$')
    software_version: str = Field(max_length=32, pattern=r'^[0-9]+\.[0-9]+\.[0-9]+$')
    environment: Literal['production', 'staging']
    key_rotation_enabled: StrictBool | None = None


class ReviewMetadata(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    title: str = Field(max_length=200)
    service: str = Field(max_length=200)
    environment: str = Field(max_length=200)
    version_min: str = Field(max_length=200)
    version_max_exclusive: str = Field(max_length=200)
    key_rotation_enabled: str = Field(max_length=200)


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    expected_revision: int = Field(ge=0, lt=100)
    metadata: ReviewMetadata


class SubmissionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    revision: int = Field(ge=1, le=100)


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    decision: Literal['approved', 'changes_requested']
    comment: str = Field(min_length=1, max_length=2000)


def create_app(*, key_file=KEY_FILE, document_loader=load_authorized_documents,
               revision_loader=load_authorized_revision, oidc_file=OIDC_FILE, oidc_provider=None,
               draft_writer=create_draft, draft_lister=list_drafts, draft_reader=get_draft, review_writer=save_review, reviewers_file=submissions.REVIEWERS_FILE):
    app = FastAPI(title='Runreviq local API', docs_url=None, redoc_url=None, openapi_url=None)
    bearer = HTTPBearer(auto_error=False)
    # Mode is fixed at startup. Removing a configured file fails closed, not back
    # to demo keys. Restart explicitly to change modes.
    sessions = GoogleSessions(Path(oidc_file), oidc_provider) if oidc_file and Path(oidc_file).exists() else None
    if sessions:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1'])
    install_routes(app, sessions)

    @app.middleware('http')
    async def no_cache(request, call_next):
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        # Framework defaults echo invalid inputs; never reflect credentials or source text.
        return JSONResponse(status_code=422, content={'detail': 'Invalid request fields or values'})

    def identity(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if sessions:
            return sessions.principal(request)
        unauthorized = HTTPException(401, 'Valid bearer credentials required',
                                     headers={'WWW-Authenticate': 'Bearer'})
        if credentials is None or len(credentials.credentials) > 256:
            raise unauthorized
        try:
            records = read_keys(key_file)
        except (OSError, ValueError):
            raise HTTPException(503, 'Authentication unavailable') from None
        supplied = hashlib.sha256(credentials.credentials.encode()).digest()
        for record in records:
            expected = hashlib.sha256(record['token'].encode()).digest()
            if secrets.compare_digest(supplied, expected):
                return {'subject': record['subject'], 'role': record['role']}
        raise unauthorized

    def draft_owner(principal):
        return owner_key('google' if sessions else 'demo', principal['subject'])

    @app.post('/v1/drafts', status_code=201)
    async def upload_draft(request: Request, filename: str, principal=Depends(identity)):
        if request.headers.get('content-type', '').split(';')[0].strip().lower() != 'text/markdown':
            raise HTTPException(415, 'Upload UTF-8 Markdown using text/markdown')
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > MAX_BYTES:
                raise HTTPException(413, 'Markdown file exceeds 1 MB')
            data.extend(chunk)
        try:
            content = data.decode('utf-8')
            return await run_in_threadpool(draft_writer, draft_owner(principal), filename, content)
        except DraftLimit:
            raise HTTPException(429, 'Draft limit reached (20 per account); contact the local operator') from None
        except (UnicodeError, DraftInputError):
            raise HTTPException(422, 'Expected nonempty UTF-8 Markdown with a simple .md filename') from None
        except (psycopg.Error, ValueError, OSError):
            raise HTTPException(503, 'Draft store unavailable') from None

    @app.get('/v1/drafts')
    def own_drafts(principal=Depends(identity)):
        try:
            return {'drafts': draft_lister(draft_owner(principal))}
        except (psycopg.Error, ValueError, OSError):
            raise HTTPException(503, 'Draft store unavailable') from None

    @app.get('/v1/drafts/{draft_id}')
    def own_draft(draft_id: UUID, principal=Depends(identity)):
        try:
            result = draft_reader(draft_owner(principal), draft_id)
        except (psycopg.Error, ValueError, OSError):
            raise HTTPException(503, 'Draft store unavailable') from None
        if result is None:
            raise HTTPException(404, 'Draft not found')
        return result

    @app.post('/v1/drafts/{draft_id}/review')
    def review_draft(draft_id: UUID, body: ReviewRequest, principal=Depends(identity)):
        try:
            result = review_writer(draft_owner(principal), draft_id, body.expected_revision, body.metadata.model_dump())
        except ReviewConflict:
            raise HTTPException(409, 'Draft review changed; reload before saving') from None
        except DraftInputError:
            raise HTTPException(422, 'Invalid review fields') from None
        except (psycopg.Error, ValueError, OSError):
            raise HTTPException(503, 'Draft store unavailable') from None
        if result is None:
            raise HTTPException(404, 'Draft not found')
        return result

    def workflow_call(function, *args):
        try:
            result = function(*args)
        except ReviewConflict:
            raise HTTPException(409, 'Revision changed or submission already decided; reload') from None
        except DraftInputError:
            raise HTTPException(422, 'Complete valid metadata or supply a nonempty decision comment') from None
        except (psycopg.Error, ValueError, OSError):
            raise HTTPException(503, 'Review service unavailable') from None
        if result is None:
            raise HTTPException(404, 'Submission or draft not found')
        return result

    def reviewer_access(principal):
        try:
            return submissions.can_review('google' if sessions else 'demo', principal['subject'], reviewers_file)
        except (ValueError, OSError):
            raise HTTPException(503, 'Reviewer configuration unavailable') from None

    def reviewer(principal=Depends(identity)):
        if not reviewer_access(principal):
            raise HTTPException(403, 'Reviewer permission must be assigned separately by the operator')
        return draft_owner(principal)

    @app.get('/v1/reviewer-access')
    def review_access(principal=Depends(identity)):
        return {'can_review': reviewer_access(principal)}

    @app.post('/v1/drafts/{draft_id}/submit')
    def submit_draft(draft_id: UUID, body: SubmissionRequest, principal=Depends(identity)):
        return workflow_call(submissions.submit, draft_owner(principal), draft_id, body.revision)

    @app.get('/v1/drafts/{draft_id}/submissions')
    def draft_submissions(draft_id: UUID, principal=Depends(identity)):
        return {'submissions': workflow_call(submissions.own_submissions, draft_owner(principal), draft_id)}

    @app.get('/v1/submissions')
    def pending_submissions(actor=Depends(reviewer)):
        return {'submissions': workflow_call(submissions.review_queue, actor)}

    @app.get('/v1/submissions/{submission_id}')
    def submitted_revision(submission_id: UUID, actor=Depends(reviewer)):
        return workflow_call(submissions.submission_detail, actor, submission_id)

    @app.post('/v1/submissions/{submission_id}/decision')
    def submission_decision(submission_id: UUID, body: DecisionRequest, actor=Depends(reviewer)):
        return workflow_call(submissions.decide, actor, submission_id, body.decision, body.comment)

    @app.get('/', include_in_schema=False)
    def workspace():
        return FileResponse(ROOT / 'runreviq/web/index.html', media_type='text/html')

    @app.get('/assets/{asset}', include_in_schema=False)
    def asset_file(asset: str):
        if asset not in ('app.js', 'app.css', 'theme.js'):
            raise HTTPException(404, 'Asset not found')
        return FileResponse(ROOT / 'runreviq/web' / asset,
                            media_type='text/javascript' if asset.endswith('.js') else 'text/css')

    @app.get('/health')
    def health():
        # Liveness only; no database or credential details.
        return {'status': 'ok'}

    @app.get('/v1/me')
    def me(principal=Depends(identity)):
        return principal

    @app.post('/v1/select')
    def selection(query: SelectionRequest, principal=Depends(identity)):
        try:
            documents = document_loader(principal['role'])
        except (psycopg.Error, ValueError, OSError):
            raise HTTPException(503, 'Evidence store unavailable') from None
        return select(documents, role=principal['role'], **query.model_dump())

    @app.get('/v1/documents/{document_id}/revisions/{revision}')
    def document_revision(document_id: str = ApiPath(pattern=r'^[A-Z]+-[0-9]+$'),
                          revision: int = ApiPath(ge=1, le=2147483647),
                          principal=Depends(identity)):
        try:
            evidence = revision_loader(principal['role'], document_id, revision)
        except (psycopg.Error, ValueError, OSError):
            raise HTTPException(503, 'Evidence store unavailable') from None
        if evidence is None:
            # Identical response for missing documents, missing revisions, and denied access.
            raise HTTPException(404, 'Document revision not found')
        return evidence

    return app


def main():
    parser = argparse.ArgumentParser(description='Manage the loopback-only Runreviq demo API')
    parser.add_argument('command', choices=['init-keys', 'serve'])
    args = parser.parse_args()
    if args.command == 'init-keys':
        try:
            initialize_keys()
        except FileExistsError:
            parser.exit(1, 'Credentials already exist; left unchanged.\n')
        print('Created owner-only credentials in .local/api-keys.json. Keep this file private.')
    else:
        try:
            if OIDC_FILE.exists():
                GoogleSessions(OIDC_FILE).config()
            else:
                read_keys(KEY_FILE)
        except (OSError, ValueError, HTTPException):
            parser.exit(1, 'Valid owner-only Google configuration or demo keys required; see SETUP.md.\n')
        import uvicorn
        uvicorn.run(create_app(), host='127.0.0.1', port=8000, access_log=False,
                    proxy_headers=False)


if __name__ == '__main__':
    main()
