import copy
import json
import unittest
from opslens.selector import ROOT, load_documents, select


class SelectorTests(unittest.TestCase):
    def setUp(self):
        self.docs = load_documents()

    def query(self, **changes):
        args = dict(role="platform", service="identity-service", software_version="2.4.0",
                    environment="production", key_rotation_enabled=True)
        args.update(changes)
        return select(self.docs, **args)

    def test_current_compatible_guidance(self):
        result = self.query()
        self.assertEqual(result["status"], "selected")
        self.assertEqual(result["recommended_documents"], ["RB-042", "RB-043"])

    def test_explains_conflicting_rules_with_authorized_references(self):
        result = self.query(software_version="2.5.0")
        detail = result["conflict_details"][0]
        self.assertEqual(detail["action"], "disable_key_rotation")
        self.assertEqual(detail["basis"], "catalog_rules")
        self.assertEqual([d["rules"] for d in detail["documents"]], [["must"], ["must_not"]])
        self.assertEqual([d["document_id"] for d in detail["documents"]], ["RB-050", "RB-051"])
        self.assertTrue(result["message"])
        self.assertTrue(result["next_steps"])

    def test_missing_context_asks_one_actionable_question(self):
        result = self.query(key_rotation_enabled=None)
        self.assertEqual(len(result["questions"]), 1)
        self.assertEqual(result["questions"][0]["field"], "key_rotation_enabled")
        self.assertEqual(result["review_items"], [])

    def test_review_distinguished_from_missing_user_context(self):
        result = self.query(software_version="2.6.0")
        self.assertEqual(result["questions"], [])
        self.assertEqual(result["review_items"][0]["reasons"], ["metadata_unverified", "missing_environment"])
        both = self.query(software_version="2.6.0", key_rotation_enabled=None)
        self.assertTrue(both["questions"])
        self.assertTrue(both["review_items"])

    def test_insufficient_evidence_does_not_disclose_hidden_documents(self):
        result = self.query(role="intern")
        self.assertIn("you can access", result["message"])
        self.assertEqual(result["review_items"], [])
        self.assertEqual(result["conflict_details"], [])
        self.assertEqual(result["questions"], [])
        self.assertNotIn("RB-042", json.dumps(result))

    def test_hidden_uncertainty_cannot_leak_into_explanations(self):
        before = self.query(key_rotation_enabled=None)
        hidden = copy.deepcopy(self.docs[4])
        hidden.update(metadata_verified=False, environment=None)
        self.docs.append(hidden)
        self.assertEqual(before, self.query(key_rotation_enabled=None))

    def test_old_version(self):
        self.assertEqual(self.query(software_version="2.1.0")["recommended_documents"], ["RB-017"])

    def test_upper_boundary_is_exclusive(self):
        self.assertEqual(self.query(software_version="2.2.0")["status"], "insufficient_evidence")

    def test_conflicting_same_context_guidance(self):
        result = self.query(software_version="2.5.0")
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(result["conflicts"], [["RB-050", "RB-051"]])
        self.assertEqual(result["recommended_documents"], [])

    def test_unknown_precondition(self):
        result = self.query(key_rotation_enabled=None)
        self.assertEqual(result["status"], "needs_context_or_review")
        self.assertEqual(result["recommended_documents"], [])

    def test_false_precondition(self):
        self.assertEqual(self.query(key_rotation_enabled=False)["status"], "insufficient_evidence")

    def test_unverified_metadata(self):
        self.assertEqual(self.query(software_version="2.6.0")["status"], "needs_context_or_review")

    def test_intern_cannot_see_production_evidence(self):
        result = self.query(role="intern")
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertEqual(result["evidence"], [])
        self.assertEqual(result["uncertain_documents"], [])

    def test_intern_staging(self):
        self.assertEqual(self.query(role="intern", environment="staging")["recommended_documents"], ["RB-044"])

    def test_security_role(self):
        self.assertIn("SEC-021", self.query(role="security")["recommended_documents"])
        self.assertNotIn("SEC-021", json.dumps(self.query()))

    def test_hidden_document_does_not_change_output(self):
        before = self.query()
        hidden = copy.deepcopy(self.docs[4])
        hidden.update(id="HIDDEN-CONFLICT", claims=[dict(action="validate_jwks", rule="must_not")])
        self.docs.append(hidden)
        self.assertEqual(before, self.query())

    def test_revocation_on_next_query(self):
        self.docs[1]["allowed_roles"] = ["security"]
        self.assertNotIn("RB-042", json.dumps(self.query()))

    def test_revoked_document_excluded(self):
        self.assertNotIn("RB-070", json.dumps(self.query()))

    def test_invalid_inputs(self):
        for args in [dict(software_version="2.4"), dict(role="admin"), dict(environment="unknown"), dict(key_rotation_enabled="true")]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.query(**args)

    def test_unknown_service(self):
        self.assertEqual(self.query(service="billing-service")["status"], "insufficient_evidence")

    def test_all_evidence_files_exist(self):
        for doc in self.docs:
            self.assertIn(doc["id"], (ROOT / doc["path"]).read_text())


if __name__ == "__main__":
    unittest.main()
