"""Original documentation is preserved for display without changing retrieval inputs."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.services.soep_rag_advisor import SOEPRagAdvisorService


class DescriptionDisplayTests(unittest.TestCase):
    def test_original_line_breaks_do_not_change_retrieval_document(self):
        # Normalization is pure; neither model loading nor respondent data is required.
        service = SOEPRagAdvisorService.__new__(SOEPRagAdvisorService)
        raw = {
            'dataset': 'pl', 'variable_name': 'pltest', 'label': 'Example measure',
            'soep_version': 'v41', 'rich_description': (
                'Example measure.\nOfficial note: Monthly, not annual.\n'
                'Question wording: How often?\nAntwortkategorien: 1: Yes; 2: No'),
            'search_description': 'Example measure. Monthly, not annual.',
        }
        row = service._normalise_soep_row(raw)
        self.assertEqual(row['description_original'], raw['rich_description'])
        self.assertNotIn('\n', row['rich_description'])
        previous = {key: value for key, value in row.items() if key != 'description_original'}
        self.assertEqual(service._build_doc(row), service._build_doc(previous))


if __name__ == '__main__':
    unittest.main()
