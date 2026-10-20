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
        self.client = TestClient(create_app(key_file=self.path, document_loader=self.loader))
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

    def test_health_is_liveness_only(self):
        self.assertEqual(self.client.get('/health').json(), {'status': 'ok'})
        self.loader.assert_not_called()
