"""Run in geolab-rag: provider identities separate study-local variable codes."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.services.soep_rag_advisor import SOEPRagAdvisorService


class ResourceIdentityTests(unittest.TestCase):
    def test_provider_field_cannot_change_soep_or_inkar_identity(self):
        for source in ("soep", "inkar"):
            row = {"source_key": source, "variable_name": "v1", "label": "Same"}
            extended = {**row, "metadata_resource_uri": "https://example.org/ignored"}
            self.assertEqual(SOEPRagAdvisorService._dedup_key(row), SOEPRagAdvisorService._dedup_key(extended))

    def test_same_code_and_label_in_two_studies_remains_two_variables(self):
        row = {"source_key": "gesis", "variable_name": "v1", "label": "Bundesland"}
        first = {**row, "metadata_resource_uri": "https://example.org/study-A-v1"}
        second = {**row, "metadata_resource_uri": "https://example.org/study-B-v1"}
        self.assertNotEqual(SOEPRagAdvisorService._dedup_key(first), SOEPRagAdvisorService._dedup_key(second))
        self.assertEqual(SOEPRagAdvisorService._dedup_key(first), SOEPRagAdvisorService._dedup_key(dict(first)))

    def test_existing_geodb_identity_is_unchanged(self):
        row = {"source_key": "existing", "variable_name": "CODE", "label": "Same label"}
        self.assertEqual(SOEPRagAdvisorService._dedup_key(row), ("existing", "code", "same label"))
        self.assertEqual(SOEPRagAdvisorService._dedup_key({"source_key": "inkar", "variable_name": "CODE"}), ("inkar", "code"))


if __name__ == "__main__":
    unittest.main()
