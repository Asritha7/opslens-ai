"""Google OIDC for the single-process, loopback-only workspace.

Provider tokens never become application bearer tokens. Only random, HttpOnly
session identifiers leave the backend; current role assignments are reloaded.
"""
import base64
import hashlib
import json
import os
import secrets
import stat
import threading
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import jwt
from fastapi import HTTPException, Request as WebRequest
from fastapi.responses import RedirectResponse

from runreviq.selector import ROLES

ORIGIN = 'http://127.0.0.1:8000'
CALLBACK = ORIGIN + '/auth/google/callback'
ISSUER = 'https://accounts.google.com'
AUTH_URL = ISSUER + '/o/oauth2/v2/auth'
TOKEN_URL = 'https://oauth2.googleapis.com/token'
JWKS_URL = 'https://www.googleapis.com/oauth2/v3/certs'
SESSION_COOKIE = 'runreviq_session'
FLOW_COOKIE = 'runreviq_login'


def read_config(path):
    with path.open() as stream:
        if stat.S_IMODE(os.fstat(stream.fileno()).st_mode) & 0o077:
            raise ValueError('Configuration must be owner-only')
        config = json.load(stream)
    if not isinstance(config, dict) or set(config) != {'client_id', 'client_secret', 'allowed_subjects'}:
        raise ValueError('Invalid configuration')
    for key in ('client_id', 'client_secret'):
        if not isinstance(config[key], str) or not config[key].strip():
            raise ValueError('Missing client credentials')
    roles = config['allowed_subjects']
    if not isinstance(roles, dict) or any(not isinstance(s, str) or not s or len(s) > 255 or not isinstance(r, str) or r not in ROLES for s, r in roles.items()):
        raise ValueError('Invalid subject assignments')
    return config


class GoogleProvider:
    def __init__(self):
        self.keys = jwt.PyJWKClient(JWKS_URL, timeout=10)

    def exchange(self, code, verifier, config):
        body = urlencode({'code': code, 'code_verifier': verifier,
                          'client_id': config['client_id'], 'client_secret': config['client_secret'],
                          'redirect_uri': CALLBACK, 'grant_type': 'authorization_code'}).encode()
        request = Request(TOKEN_URL, data=body, headers={'Content-Type': 'application/x-www-form-urlencoded'})
        with urlopen(request, timeout=10) as response:
            data = json.loads(response.read(131073))
        return data['id_token']

    def verify(self, token, nonce, config):
        if not isinstance(token, str) or len(token) > 32768:
            raise ValueError('Invalid token')
        key = self.keys.get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=['RS256'], audience=config['client_id'],
                            issuer=[ISSUER, 'accounts.google.com'],
                            options={'require': ['iss', 'sub', 'aud', 'exp', 'iat', 'nonce']})
        if (not isinstance(claims['nonce'], str) or not secrets.compare_digest(claims['nonce'], nonce)
                or not isinstance(claims['sub'], str) or not claims['sub'] or len(claims['sub']) > 255
                or claims.get('azp', config['client_id']) != config['client_id']
                or type(claims['exp']) not in (int, float) or type(claims['iat']) not in (int, float)
                or (isinstance(claims['aud'], list) and len(claims['aud']) > 1 and 'azp' not in claims)):
            raise ValueError('Invalid identity claims')
        return claims


class GoogleSessions:
    def __init__(self, path, provider=None, clock=time.time):
        self.path, self.provider, self.clock = path, provider or GoogleProvider(), clock
        self.pending, self.sessions = {}, {}
        self.lock = threading.Lock()

    def config(self):
        try:
            return read_config(self.path)
        except (OSError, ValueError, TypeError):
            raise HTTPException(503, 'Google login configuration unavailable') from None

    def prune(self):
        for store in (self.pending, self.sessions):
            for key in list(store):
                if store[key]['expires'] <= self.clock():
                    del store[key]

    @staticmethod
    def digest(value):
        return hashlib.sha256(value.encode()).hexdigest()

    def check_origin(self, request):
        if request.headers.get('origin') != ORIGIN or request.headers.get('x-runreviq-request') != '1':
            raise HTTPException(403, 'Same-origin request required')

    def start(self, request):
        config = self.config()
        state, nonce, verifier, binding = (secrets.token_urlsafe(32) for _ in range(4))
        with self.lock:
            self.prune()
            if len(self.pending) >= 1000:
                raise HTTPException(503, 'Too many pending logins')
            self.pending[self.digest(state)] = {'nonce': nonce, 'verifier': verifier,
                'binding': self.digest(binding), 'client_id': config['client_id'], 'expires': self.clock() + 600}
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        response = RedirectResponse(AUTH_URL + '?' + urlencode({'client_id': config['client_id'],
            'redirect_uri': CALLBACK, 'response_type': 'code', 'scope': 'openid', 'state': state,
            'nonce': nonce, 'code_challenge': challenge, 'code_challenge_method': 'S256', 'prompt': 'select_account'}), status_code=303)
        response.set_cookie(FLOW_COOKIE, binding, max_age=600, httponly=True, samesite='lax', path='/auth/google')
        return response

    def callback(self, request):
        # Consume the flow even on rejection: callback and code replay cannot create sessions.
        state = request.query_params.get('state', '')
        binding = request.cookies.get(FLOW_COOKIE, '')
        with self.lock:
            self.prune()
            flow = self.pending.pop(self.digest(state), None)
        response = RedirectResponse('/?login=failed', status_code=303)
        response.delete_cookie(FLOW_COOKIE, path='/auth/google')
        if (not flow or not binding or not secrets.compare_digest(flow['binding'], self.digest(binding))
                or request.query_params.get('error') or not request.query_params.get('code')
                or len(request.query_params.getlist('state')) != 1 or len(request.query_params.getlist('code')) != 1):
            return response
        config = self.config()
        if config['client_id'] != flow['client_id']:
            return response
        try:
            token = self.provider.exchange(request.query_params['code'], flow['verifier'], config)
            claims = self.provider.verify(token, flow['nonce'], config)
        except Exception:
            # Never echo upstream response bodies, codes, credentials, or JWTs.
            return response
        session = secrets.token_urlsafe(32)
        with self.lock:
            self.prune()
            if len(self.sessions) >= 1000:
                raise HTTPException(503, 'Too many active sessions')
            self.sessions.pop(self.digest(request.cookies.get(SESSION_COOKIE, '')), None)
            self.sessions[self.digest(session)] = {'subject': claims['sub'], 'client_id': config['client_id'],
                'expires': min(self.clock() + 3600, claims['exp'])}
        response.headers['location'] = '/'
        response.set_cookie(SESSION_COOKIE, session, max_age=3600, httponly=True, samesite='lax', path='/')
        return response

    def principal(self, request, require_role=True):
        config = self.config()
        with self.lock:
            self.prune()
            session = self.sessions.get(self.digest(request.cookies.get(SESSION_COOKIE, '')))
        if not session or session['client_id'] != config['client_id']:
            raise HTTPException(401, 'Sign in with Google to continue')
        role = config['allowed_subjects'].get(session['subject'])
        if require_role and role is None:
            raise HTTPException(403, 'This Google account has no assigned Runreviq role')
        if request.method not in ('GET', 'HEAD'):
            self.check_origin(request)
        return {'subject': session['subject'], 'role': role}

    def logout(self, request):
        self.check_origin(request)
        with self.lock:
            self.sessions.pop(self.digest(request.cookies.get(SESSION_COOKIE, '')), None)
        response = RedirectResponse('/', status_code=303)
        response.delete_cookie(SESSION_COOKIE, path='/')
        return response


def install_routes(app, sessions):
    @app.get('/auth/config')
    def auth_config():
        if sessions:
            sessions.config()
        return {'mode': 'google' if sessions else 'demo'}

    if not sessions:
        return

    @app.get('/auth/google/login')
    def login(request: WebRequest):
        return sessions.start(request)

    @app.get('/auth/google/callback')
    def callback(request: WebRequest):
        return sessions.callback(request)

    @app.get('/auth/session')
    def session(request: WebRequest):
        return sessions.principal(request, require_role=False)

    @app.post('/auth/logout')
    def logout(request: WebRequest):
        # JSON avoids fetch following a redirect during logout.
        response = sessions.logout(request)
        response.status_code = 204
        del response.headers['location']
        return response


def main():
    """Prompt locally, keeping credentials out of shell arguments and history."""
    import getpass
    from runreviq.selector import ROOT
    path = ROOT / '.local/google-oidc.json'
    if path.exists():
        raise SystemExit('Google configuration already exists; left unchanged.')
    client_id = input('Google Web client ID: ').strip()
    client_secret = getpass.getpass('Google client secret (hidden): ').strip()
    if not client_id or not client_secret:
        raise SystemExit('Both values are required; no file created.')
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump({'client_id': client_id, 'client_secret': client_secret, 'allowed_subjects': {}}, stream, indent=2)
        stream.write('\n')
    print('Created private Google configuration with no role assignments. Restart the API, sign in, then assign your verified subject locally.')


if __name__ == '__main__':
    main()
