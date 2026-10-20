"""Loopback-only demo API. Bearer credentials determine the database reader role."""
import argparse
import hashlib
import json
import os
import secrets
import stat
from pathlib import Path
from typing import Literal

import psycopg
from fastapi import Depends, FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from opslens.database import load_authorized_documents
from opslens.selector import ROOT, ROLES, select

KEY_FILE = ROOT / '.local/api-keys.json'


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


def create_app(*, key_file=KEY_FILE, document_loader=load_authorized_documents):
    app = FastAPI(title='OpsLens local API', docs_url=None, redoc_url=None, openapi_url=None)
    bearer = HTTPBearer(auto_error=False)

    @app.middleware('http')
    async def no_cache(request, call_next):
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        # Framework defaults echo invalid inputs; never reflect credentials or source text.
        return JSONResponse(status_code=422, content={'detail': 'Invalid request fields or values'})

    def identity(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
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

    return app


def main():
    parser = argparse.ArgumentParser(description='Manage the loopback-only OpsLens demo API')
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
            read_keys(KEY_FILE)
        except (OSError, ValueError):
            parser.exit(1, 'Valid owner-only credentials required; run init-keys first.\n')
        import uvicorn
        uvicorn.run(create_app(), host='127.0.0.1', port=8000, access_log=False,
                    proxy_headers=False)


if __name__ == '__main__':
    main()
