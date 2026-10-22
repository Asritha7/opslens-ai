"""Offline OIDC security regressions: no Google account or external calls."""
import json
import base64
import hashlib
from pathlib import Path
import tempfile
import time
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest.mock import Mock

from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
import jwt

from opslens.api import create_app
from opslens.oidc import GoogleProvider, GoogleSessions, ISSUER, ORIGIN, SESSION_COOKIE, FLOW_COOKIE
from tests.test_api import QUERY


class OidcTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'google.json'
        self.config = {'client_id': 'test-client', 'client_secret': 'test-secret', 'allowed_subjects': {'user-1': 'platform'}}
        self.save()
        self.provider = Mock()
        self.provider.exchange.return_value = 'provider-token'
        self.provider.verify.side_effect = lambda token, nonce, config: {'sub': 'user-1', 'exp': time.time() + 3600}
        self.loader = Mock(return_value=[])
        self.client = TestClient(create_app(oidc_file=self.path, oidc_provider=self.provider, document_loader=self.loader), base_url=ORIGIN)
        self.addCleanup(self.client.close)
        self.headers = {'Origin': ORIGIN, 'X-OpsLens-Request': '1'}

    def save(self):
        self.path.write_text(json.dumps(self.config))
        self.path.chmod(0o600)

    def start(self):
        response = self.client.get('/auth/google/login', follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        return parse_qs(urlsplit(response.headers['location']).query)

    def login(self):
        flow = self.start()
        return self.client.get('/auth/google/callback', params={'state': flow['state'][0], 'code': 'test-code'}, follow_redirects=False)

    def test_mode_and_flow_parameters(self):
        self.assertEqual(self.client.get('/auth/config').json(), {'mode': 'google'})
        flow = self.start()
        self.assertEqual(flow['scope'], ['openid'])
        self.assertEqual(flow['code_challenge_method'], ['S256'])
        self.assertEqual(flow['redirect_uri'], [ORIGIN + '/auth/google/callback'])
        self.assertNotIn('client_secret', flow)

    def test_session_is_opaque_and_cookie_is_httponly(self):
        response = self.login()
        self.assertEqual(response.headers['location'], '/')
        cookies = response.headers.get_list('set-cookie')
        self.assertTrue(any('HttpOnly' in c and 'SameSite=lax' in c and SESSION_COOKIE in c for c in cookies))
        self.assertNotIn('provider-token', str(cookies))
        self.assertEqual(self.client.get('/v1/me').json(), {'subject': 'user-1', 'role': 'platform'})
        self.assertEqual(self.client.post('/v1/select', json=QUERY, headers=self.headers).status_code, 200)
        self.loader.assert_called_once_with('platform')

    def test_pkce_verifier_and_nonce_are_bound_to_started_flow(self):
        flow = self.start()
        self.client.get('/auth/google/callback', params={'state': flow['state'][0], 'code': 'code'}, follow_redirects=False)
        verifier = self.provider.exchange.call_args.args[1]
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        self.assertEqual(flow['code_challenge'], [challenge])
        self.assertEqual(self.provider.verify.call_args.args[1], flow['nonce'][0])

    def test_new_login_replaces_previous_browser_session(self):
        self.login()
        old = self.client.cookies.get(SESSION_COOKIE)
        self.login()
        self.assertNotEqual(old, self.client.cookies.get(SESSION_COOKIE))
        self.assertEqual(self.client.get('/v1/me', headers={'Cookie': f'{SESSION_COOKIE}={old}'}).status_code, 401)

    def test_missing_or_wrong_browser_binding_rejected(self):
        flow = self.start()
        self.client.cookies.clear()
        response = self.client.get('/auth/google/callback', params={'state': flow['state'][0], 'code': 'code'}, follow_redirects=False)
        self.assertEqual(response.headers['location'], '/?login=failed')
        self.provider.exchange.assert_not_called()

    def test_state_replay_rejected(self):
        flow = self.start()
        params = {'state': flow['state'][0], 'code': 'code'}
        self.client.get('/auth/google/callback', params=params, follow_redirects=False)
        self.assertEqual(self.client.get('/auth/google/callback', params=params, follow_redirects=False).headers['location'], '/?login=failed')
        self.assertEqual(self.provider.exchange.call_count, 1)

    def test_provider_denial_and_failure_are_safe(self):
        flow = self.start()
        self.client.get('/auth/google/callback', params={'state': flow['state'][0], 'error': 'access_denied'}, follow_redirects=False)
        self.provider.exchange.assert_not_called()
        self.provider.exchange.side_effect = ValueError('secret-upstream-body')
        response = self.login()
        self.assertEqual(response.headers['location'], '/?login=failed')
        self.assertNotIn('secret-upstream-body', response.text)
        self.assertEqual(self.client.get('/v1/me').status_code, 401)

    def test_unassigned_account_sees_subject_but_no_evidence(self):
        self.config['allowed_subjects'] = {}
        self.save(); self.login()
        self.assertEqual(self.client.get('/auth/session').json(), {'subject': 'user-1', 'role': None})
        self.assertEqual(self.client.get('/v1/me').status_code, 403)
        self.assertEqual(self.client.post('/v1/select', json=QUERY, headers=self.headers).status_code, 403)
        self.loader.assert_not_called()

    def test_role_changes_and_revocation_apply_to_existing_session(self):
        self.login()
        self.config['allowed_subjects']['user-1'] = 'intern'; self.save()
        self.assertEqual(self.client.get('/v1/me').json()['role'], 'intern')
        self.config['allowed_subjects'] = {}; self.save()
        self.assertEqual(self.client.get('/v1/me').status_code, 403)

    def test_csrf_and_host_checks(self):
        self.login()
        for headers in ({}, {'Origin': 'https://evil.example', 'X-OpsLens-Request': '1'}, {'Origin': ORIGIN}):
            self.assertEqual(self.client.post('/v1/select', json=QUERY, headers=headers).status_code, 403)
            self.assertEqual(self.client.post('/auth/logout', headers=headers).status_code, 403)
        self.assertEqual(self.client.get('/auth/session', headers={'Host': 'evil.example'}).status_code, 400)
        self.loader.assert_not_called()

    def test_logout_revokes_copied_session_cookie(self):
        self.login()
        cookie = self.client.cookies.get(SESSION_COOKIE)
        self.assertEqual(self.client.post('/auth/logout', headers=self.headers).status_code, 204)
        self.assertEqual(self.client.get('/v1/me', headers={'Cookie': f'{SESSION_COOKIE}={cookie}'}).status_code, 401)

    def test_bearer_cannot_bypass_google_mode(self):
        self.assertEqual(self.client.get('/v1/me', headers={'Authorization': 'Bearer ' + 'a'*43}).status_code, 401)

    def test_config_removal_or_unsafe_permissions_fails_closed(self):
        self.login(); self.path.chmod(0o644)
        self.assertEqual(self.client.get('/v1/me').status_code, 503)
        self.path.unlink()
        self.assertEqual(self.client.get('/auth/config').status_code, 503)
        self.assertEqual(self.client.get('/v1/me').status_code, 503)

    def test_client_change_invalidates_session(self):
        self.login(); self.config['client_id'] = 'different-client'; self.save()
        self.assertEqual(self.client.get('/v1/me').status_code, 401)

    def test_expired_state_and_sessions_are_removed(self):
        now = [100]
        sessions = GoogleSessions(self.path, self.provider, clock=lambda: now[0])
        sessions.pending['state'] = {'expires': 101}
        sessions.sessions['cookie'] = {'expires': 101}
        now[0] = 102
        sessions.prune()
        self.assertFalse(sessions.pending); self.assertFalse(sessions.sessions)


class TokenValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def setUp(self):
        self.provider = GoogleProvider()
        self.provider.keys = Mock()
        self.provider.keys.get_signing_key_from_jwt.return_value.key = self.key.public_key()
        self.config = {'client_id': 'client'}
        self.claims = {'iss': ISSUER, 'sub': 'user', 'aud': 'client', 'iat': int(time.time()), 'exp': int(time.time()) + 60, 'nonce': 'nonce'}

    def verify(self, **changes):
        claims = {**self.claims, **changes}
        token = jwt.encode(claims, self.key, algorithm='RS256')
        return self.provider.verify(token, 'nonce', self.config)

    def test_valid_signed_token(self):
        self.assertEqual(self.verify()['sub'], 'user')

    def test_invalid_identity_claims(self):
        for changes in ({'iss': 'https://evil.example'}, {'aud': 'other'}, {'exp': 1}, {'iat': int(time.time()) + 999}, {'nonce': 'other'}, {'sub': ''}, {'azp': 'other'}, {'aud': ['client', 'other']}):
            with self.subTest(changes=changes), self.assertRaises((jwt.PyJWTError, ValueError)):
                self.verify(**changes)

    def test_missing_required_claim(self):
        for claim in ('iss', 'sub', 'aud', 'exp', 'iat', 'nonce'):
            claims = dict(self.claims); claims.pop(claim)
            with self.subTest(claim=claim), self.assertRaises(jwt.PyJWTError):
                self.provider.verify(jwt.encode(claims, self.key, algorithm='RS256'), 'nonce', self.config)

    def test_bad_signature_and_unsigned_tokens(self):
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        for token in (jwt.encode(self.claims, other, algorithm='RS256'), jwt.encode(self.claims, '', algorithm='none')):
            with self.assertRaises(jwt.PyJWTError):
                self.provider.verify(token, 'nonce', self.config)
