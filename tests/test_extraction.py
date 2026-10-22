import hashlib
import unittest

from runreviq.extraction import extract

SOURCE = '''# Example runbook

## Applicability
service: identity-service
environment: production
version_min: 2.4.0
version_max_exclusive: 2.5.0
key_rotation_enabled: true

## Procedure
Follow the reviewed procedure.
'''


class ExtractionTests(unittest.TestCase):
    def test_explicit_fields_have_exact_line_provenance(self):
        result = extract(SOURCE)
        self.assertEqual(result['proposed_metadata']['environment'], 'production')
        self.assertTrue(result['proposed_metadata']['key_rotation_enabled'])
        self.assertEqual(result['issues'], [])
        self.assertTrue(result['review_required'])
        self.assertEqual(result['source_sha256'], hashlib.sha256(SOURCE.encode()).hexdigest())
        for entries in result['provenance'].values():
            for entry in entries:
                self.assertEqual(SOURCE.splitlines()[entry['line'] - 1], entry['quote'])

    def test_ambiguous_titles_keep_review_evidence(self):
        result = extract(SOURCE + '\n# Another title\n')
        self.assertNotIn('title', result['proposed_metadata'])
        self.assertEqual(len(result['provenance']['title']), 2)
        self.assertIn({'field': 'title', 'reason': 'missing_or_ambiguous'}, result['issues'])

    def test_prose_is_not_guessed(self):
        result = extract('# Runbook\nMaybe production for 2.4? Rotation might be on.')
        self.assertEqual(result['proposed_metadata'], {'title': 'Runbook'})
        self.assertEqual(len(result['issues']), 5)

    def test_duplicate_values_are_ambiguous_even_when_identical(self):
        for value in ('production', 'staging'):
            result = extract(SOURCE.replace('environment: production', f'environment: production\nenvironment: {value}'))
            self.assertNotIn('environment', result['proposed_metadata'])
            self.assertIn({'field': 'environment', 'reason': 'ambiguous'}, result['issues'])
            self.assertEqual(len(result['provenance']['environment']), 2)

    def test_invalid_values_not_proposed(self):
        for old, new, field in [('2.4.0', '2.4', 'version_min'),
                                ('production', 'unknown', 'environment'),
                                ('identity-service', 'two services', 'service'),
                                ('true', 'maybe', 'key_rotation_enabled')]:
            with self.subTest(field=field):
                result = extract(SOURCE.replace(old, new))
                self.assertNotIn(field, result['proposed_metadata'])
                self.assertIn({'field': field, 'reason': 'invalid_value'}, result['issues'])

    def test_inverted_range_requires_review(self):
        result = extract(SOURCE.replace('2.4.0', '2.6.0'))
        self.assertNotIn('version_min', result['proposed_metadata'])
        self.assertNotIn('version_max_exclusive', result['proposed_metadata'])
        self.assertIn({'field': 'version_range', 'reason': 'empty_or_inverted'}, result['issues'])

    def test_missing_requirement_distinct_from_explicit_none(self):
        result = extract(SOURCE.replace('key_rotation_enabled: true', ''))
        self.assertNotIn('key_rotation_enabled', result['proposed_metadata'])
        result = extract(SOURCE.replace('key_rotation_enabled: true', 'key_rotation_enabled: none'))
        self.assertIsNone(result['proposed_metadata']['key_rotation_enabled'])
        self.assertEqual(result['issues'], [])

    def test_document_cannot_assign_permissions_or_approval(self):
        injected = SOURCE.replace('## Procedure', 'allowed_roles: security\nstatus: approved\nmetadata_verified: true\nreview_required: false\n\n## Procedure')
        result = extract(injected)
        for field in ('allowed_roles', 'status', 'metadata_verified', 'review_required'):
            self.assertNotIn(field, result['proposed_metadata'])
        self.assertTrue(result['review_required'])

    def test_code_examples_and_other_sections_are_ignored(self):
        suffix = '\nenvironment: staging\n```\n## Applicability\nenvironment: staging\n```\n'
        self.assertEqual(extract(SOURCE + suffix)['proposed_metadata'], extract(SOURCE)['proposed_metadata'])

    def test_size_limit(self):
        with self.assertRaises(ValueError):
            extract('x' * 1_000_001)
