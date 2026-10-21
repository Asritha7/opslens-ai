import copy
import hashlib
import unittest

from opslens.citations import validate_citations
from opslens.selector import load_documents, select


class CitationTests(unittest.TestCase):
    def setUp(self):
        self.content = 'Heading\nFirst instruction.\nSecond instruction.\n'
        self.claims = [{'action': 'example', 'rule': 'must', 'citation': {
            'start_line': 2, 'end_line': 3,
            'quote': 'First instruction.\nSecond instruction.',
            'source_sha256': hashlib.sha256(self.content.encode()).hexdigest()}}]

    def test_exact_multiline_quote(self):
        validate_citations(self.claims, self.content)

    def test_invalid_ranges_and_quotes_rejected(self):
        for changes in ({'start_line': 0}, {'start_line': True}, {'end_line': 99},
                        {'start_line': 3, 'end_line': 2}, {'quote': 'Invented instruction'},
                        {'quote': ''}, {'source_sha256': 'stale'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                claims = copy.deepcopy(self.claims)
                claims[0]['citation'].update(changes)
                validate_citations(claims, self.content)

    def test_changes_outside_quote_invalidate_fingerprint(self):
        with self.assertRaises(ValueError):
            validate_citations(self.claims, self.content.replace('Heading', 'Changed heading'))

    def test_malformed_citation_rejected(self):
        for value in (None, [], {}, {'quote': 'text'}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_citations([dict(action='example', rule='must', citation=value)], self.content)

    def query(self, documents, role='platform'):
        return select(documents, role=role, service='identity-service', software_version='2.5.0',
                      environment='production', key_rotation_enabled=True)

    def test_conflict_contains_revision_bound_quotes(self):
        result = self.query(load_documents())
        self.assertEqual(result['recommended_documents'], [])
        for doc in result['conflict_details'][0]['documents']:
            self.assertEqual(doc['revision'], 2)
            self.assertEqual(doc['citation_status'], 'available')
            citation = doc['citations'][0]
            self.assertEqual(citation['document_id'], doc['document_id'])
            self.assertEqual(citation['revision'], 2)
            self.assertEqual(citation['start_line'], 7)
            self.assertEqual(citation['rule'], doc['rules'][0])

    def test_legacy_claims_report_missing_citations_without_fabrication(self):
        docs = load_documents()
        for doc in docs:
            for claim in doc['claims']:
                claim.pop('citation', None)
        result = self.query(docs)
        self.assertEqual(result['status'], 'conflict')
        for doc in result['conflict_details'][0]['documents']:
            self.assertEqual(doc['citations'], [])
            self.assertEqual(doc['citation_status'], 'incomplete')

    def test_unauthorized_quotes_not_exposed(self):
        docs = load_documents()
        for doc in docs:
            if doc['id'] in ('RB-050', 'RB-051'):
                doc['allowed_roles'] = ['security']
        result = self.query(docs)
        self.assertEqual(result['conflict_details'], [])
        self.assertEqual(result['evidence'], [])
