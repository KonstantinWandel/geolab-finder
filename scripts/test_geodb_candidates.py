"""Small deterministic tests for provider-diverse and exact-code candidate retrieval."""
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.services.soep_rag_advisor import SOEPRagAdvisorService


def service(rows, allowed=None, mode="inkar"):
    result = object.__new__(SOEPRagAdvisorService)
    result.app_mode = mode
    result._rows = rows
    result._embedder = object()
    result._embeddings = np.asarray([[r.pop("similarity")] for r in rows], dtype="float32")
    result._name_index = None
    result._label_words = set()
    keep = list(range(len(rows))) if allowed is None else allowed
    result._filtered_view = lambda filters: (keep, result._embeddings[keep])
    result._query_vector = lambda query: np.asarray([[1]], dtype="float32")
    return result


class CandidateTests(unittest.TestCase):
    def rows(self):
        return [{"item_id": str(i), "source_key": s, "variable_name": f"v{i}", "label": "Region", "similarity": 1 - i / 100}
                for i, s in enumerate(["large"] * 8 + ["small-A", "small-B", "small-C", "small-D"])]

    def test_global_head_is_preserved_and_budget_is_bounded(self):
        search = service(self.rows())
        ordinary = search._search("query", 3)
        diverse = search._search("query", 3, source_diverse=True)
        self.assertEqual(ordinary, diverse[:3])
        self.assertEqual(len(diverse), 6)
        self.assertEqual([r["source_key"] for r in diverse[3:]], ["small-A", "small-B", "small-C"])

    def test_single_source_and_empty_filter_add_no_candidates(self):
        search = service(self.rows(), list(range(8)))
        self.assertEqual(search._search("query", 3), search._search("query", 3, source_diverse=True))
        empty = service(self.rows(), [])
        self.assertEqual(empty._search("query", 3, source_diverse=True), [])

    def test_diversity_never_escapes_filter(self):
        search = service(self.rows(), [1, 2, 9])
        self.assertEqual({r["item_id"] for r in search._search("query", 2, source_diverse=True)}, {"1", "2", "9"})

    def test_codes_are_exact_not_nearby_or_plain_words(self):
        rows = [{"item_id": str(i), "source_key": "provider", "variable_name": code,
                 "label": "Population", "similarity": score}
                for i, (code, score) in enumerate([( "AB1234", .6), ("AB1235", .9), ("Population", .8)])]
        search = service(rows)
        self.assertEqual([r["variable_name"] for r in search._soep_code_rows("AB1234", {})], ["AB1234"])
        for query in ("Population", "please AB1234", "AB1236"):
            self.assertEqual(search._soep_code_rows(query, {}), [])

    def test_study_local_codes_rank_all_matching_studies_before_limit(self):
        rows = [{"item_id": str(i), "source_key": "archive", "variable_name": "var001",
                 "label": "District", "similarity": i / 100} for i in range(20)]
        search = service(rows, allowed=[0, 3, 17, 18, 19])
        self.assertEqual([r["item_id"] for r in search._soep_code_rows("var001", {}, limit=2)], ["19", "18"])

    def test_soep_code_selection_keeps_original_order(self):
        rows = [{"item_id": str(i), "source_key": "soep", "variable_name": "pgcode",
                 "label": "Income", "similarity": i / 100} for i in range(5)]
        search = service(rows, mode="soep")
        self.assertEqual([r["item_id"] for r in search._soep_code_rows("pgcode", {}, limit=2)], ["0", "1"])


if __name__ == "__main__":
    unittest.main()
