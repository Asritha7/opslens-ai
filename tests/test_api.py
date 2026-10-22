"""Exercise HTTP authentication, role binding, and safe failure responses."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

import psycopg
from fastapi.testclient import TestClient

from opslens.api import create_app, initialize_keys, read_keys
from opslens.selector import load_documents

QUERY = {'service': 'identity-service', 'software_version': '2.4.0',
         'environment': 'production', 'key_rotation_enabled': True}


class ApiTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'keys.json'
        initialize_keys(self.path)
        self.records = read_keys(self.path)
        self.loader = Mock(return_value=load_documents())
        self.revision_loader = Mock(return_value=None)
        self.client = TestClient(create_app(oidc_file=None, key_file=self.path, document_loader=self.loader, revision_loader=self.revision_loader))
        self.addCleanup(self.client.close)

    def headers(self, role='platform'):
        token = next(r['token'] for r in self.records if r['role'] == role)
        return {'Authorization': f'Bearer {token}'}

    def test_key_creation_private_and_never_overwrites(self):
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        original = self.path.read_bytes()
        with self.assertRaises(FileExistsError):
            initialize_keys(self.path)
        self.assertEqual(self.path.read_bytes(), original)

    def test_missing_invalid_and_wrong_scheme_never_load_evidence(self):
        for headers in ({}, {'Authorization': 'Bearer invalid'}, {'Authorization': 'Basic abc'},
                        {'Authorization': 'Bearer ' + 'x' * 257}):
            response = self.client.post('/v1/select', json=QUERY, headers=headers)
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.headers['www-authenticate'], 'Bearer')
        self.loader.assert_not_called()

    def test_identity_returns_no_secret(self):
        response = self.client.get('/v1/me', headers=self.headers())
        self.assertEqual(response.json(), {'subject': 'demo-platform', 'role': 'platform'})
        self.assertEqual(response.headers['cache-control'], 'no-store')

    def test_role_comes_from_key_not_request(self):
        response = self.client.post('/v1/select', json=QUERY, headers=self.headers('intern'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'insufficient_evidence')
        self.assertNotIn('SEC-021', response.text)
        self.loader.assert_called_once_with('intern')
        self.loader.reset_mock()
        response = self.client.post('/v1/select', json=dict(QUERY, role='security'), headers=self.headers('intern'))
        self.assertEqual(response.status_code, 422)
        self.loader.assert_not_called()

    def test_outcomes_preserve_selection_and_conflict(self):
        response = self.client.post('/v1/select', json=QUERY, headers=self.headers())
        self.assertEqual(response.json()['recommended_documents'], ['RB-042', 'RB-043'])
        for updates, status in (({'software_version': '2.5.0'}, 'conflict'),
                                ({'key_rotation_enabled': None}, 'needs_context_or_review')):
            response = self.client.post('/v1/select', json=dict(QUERY, **updates), headers=self.headers())
            self.assertEqual(response.json()['status'], status)
            self.assertEqual(response.json()['recommended_documents'], [])

    def test_invalid_inputs_are_not_echoed_or_loaded(self):
        for updates in ({'software_version': '2.4'}, {'software_version': '9' * 100},
                        {'key_rotation_enabled': 'true'}, {'key_rotation_enabled': 1},
                        {'environment': 'private-secret'}, {'service': ''}, {'token': 'private-secret'}):
            response = self.client.post('/v1/select', json=dict(QUERY, **updates), headers=self.headers())
            self.assertEqual(response.status_code, 422)
            self.assertNotIn('private-secret', response.text)
        self.loader.assert_not_called()

    def test_revoked_key_stops_working_immediately(self):
        self.path.write_text(json.dumps([r for r in self.records if r['role'] != 'platform']))
        self.assertEqual(self.client.get('/v1/me', headers=self.headers()).status_code, 401)

    def test_bad_or_missing_configuration_fails_closed(self):
        for value in ('invalid json', '{}', '[]', json.dumps([self.records[0]] * 2),
                      json.dumps([dict(self.records[0], role=['security'])])):
            self.path.write_text(value)
            self.assertEqual(self.client.post('/v1/select', json=QUERY, headers=self.headers()).status_code, 503)
        self.path.unlink()
        self.assertEqual(self.client.get('/v1/me', headers=self.headers()).status_code, 503)
        self.loader.assert_not_called()

    def test_world_readable_keys_rejected(self):
        os.chmod(self.path, 0o644)
        self.assertEqual(self.client.get('/v1/me', headers=self.headers()).status_code, 503)

    def test_database_errors_are_generic(self):
        self.loader.side_effect = psycopg.OperationalError('secret password and restricted content')
        response = self.client.post('/v1/select', json=QUERY, headers=self.headers())
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {'detail': 'Evidence store unavailable'})

    def test_response_exposes_user_messages_questions_and_conflicts(self):
        missing = self.client.post('/v1/select', json=dict(QUERY, key_rotation_enabled=None), headers=self.headers()).json()
        self.assertEqual(missing['questions'][0]['field'], 'key_rotation_enabled')
        self.assertTrue(missing['message'])
        conflict = self.client.post('/v1/select', json=dict(QUERY, software_version='2.5.0'), headers=self.headers()).json()
        self.assertEqual(conflict['conflict_details'][0]['action'], 'disable_key_rotation')
        self.assertEqual(conflict['recommended_documents'], [])
        cited = conflict['conflict_details'][0]['documents'][0]
        self.assertEqual(cited['citation_status'], 'available')
        self.assertEqual(cited['citations'][0]['revision'], 2)
        self.assertIn('requires disabling key rotation', cited['citations'][0]['quote'])

    def test_revision_requires_authentication_before_loading(self):
        for headers in ({}, {'Authorization': 'Bearer invalid'}):
            response = self.client.get('/v1/documents/RB-042/revisions/1', headers=headers)
            self.assertEqual(response.status_code, 401)
        self.revision_loader.assert_not_called()

    def test_revision_uses_authenticated_role_and_disables_caching(self):
        record = {'document_id': 'RB-044', 'revision': 1, 'title': 'Staging',
                  'content': '<script>untrusted source</script>', 'checksum': 'abc',
                  'current_revision': 1, 'is_current': True, 'revision_status': 'approved'}
        self.revision_loader.return_value = record
        response = self.client.get('/v1/documents/RB-044/revisions/1', headers=self.headers('intern'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), record)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(response.headers['x-content-type-options'], 'nosniff')
        self.assertIn('application/json', response.headers['content-type'])
        self.revision_loader.assert_called_once_with('intern', 'RB-044', 1)

    def test_revision_not_found_response_is_generic(self):
        for path in ('SEC-021/revisions/1', 'RB-999/revisions/1', 'RB-042/revisions/99'):
            response = self.client.get('/v1/documents/' + path, headers=self.headers())
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json(), {'detail': 'Document revision not found'})

    def test_revision_invalid_identifiers_rejected_before_loading(self):
        for path in ('bad/revisions/1', 'RB-042/revisions/0', 'RB-042/revisions/-1',
                     'RB-042/revisions/2147483648', 'RB-042/revisions/not-a-number'):
            response = self.client.get('/v1/documents/' + path, headers=self.headers())
            self.assertEqual(response.status_code, 422)
        self.revision_loader.assert_not_called()

    def test_revision_store_errors_are_sanitized(self):
        self.revision_loader.side_effect = psycopg.OperationalError('restricted source and password')
        response = self.client.get('/v1/documents/RB-042/revisions/1', headers=self.headers())
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {'detail': 'Evidence store unavailable'})

    def test_browser_shell_and_assets_have_security_headers(self):
        for url, media in (('/', 'text/html'), ('/assets/app.js', 'text/javascript'), ('/assets/app.css', 'text/css'), ('/assets/theme.js', 'text/javascript')):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertIn(media, response.headers['content-type'])
            self.assertEqual(response.headers['cache-control'], 'no-store')
            self.assertIn("frame-ancestors 'none'", response.headers['content-security-policy'])
            self.assertIn("script-src 'self'", response.headers['content-security-policy'])
            self.assertEqual(response.headers['referrer-policy'], 'no-referrer')
            for record in self.records:
                self.assertNotIn(record['token'], response.text)
        self.loader.assert_not_called()
        self.revision_loader.assert_not_called()

    def test_browser_assets_are_allowlisted(self):
        for url in ('/assets/api-keys.json', '/assets/.env', '/assets/api.py', '/assets/index.html'):
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_health_is_liveness_only(self):
        self.assertEqual(self.client.get('/health').json(), {'status': 'ok'})
        self.loader.assert_not_called()
