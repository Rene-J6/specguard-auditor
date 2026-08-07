import unittest

from scripts.evaluate_rag import calculate_metrics, choose_threshold


class RagEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.examples = [
            {"id": "1", "requirement": "a", "expected_standard": "ISO 1",
             "expected_clause": "2.1", "category": "functional"},
            {"id": "2", "requirement": "b", "expected_standard": None,
             "expected_clause": None, "category": "no_match"},
        ]
        self.rankings = [[
            {"standard": "ISO 1", "clause": "2.1", "title": "Scope",
             "text": "text", "score": 0.6},
        ], [
            {"standard": "ISO 1", "clause": "3", "title": "Testing",
             "text": "text", "score": 0.4},
        ]]

    def test_metrics_include_hits_mrr_and_no_match_rejection(self):
        metrics = calculate_metrics(self.examples, self.rankings, 0.5)
        self.assertEqual(metrics["hit_at_1"], 1)
        self.assertEqual(metrics["hit_at_5"], 1)
        self.assertEqual(metrics["mrr"], 1)
        self.assertEqual(metrics["no_match_rejection_rate"], 1)

    def test_threshold_selection_uses_validation_rules(self):
        selected, _ = choose_threshold(self.examples, self.rankings)
        self.assertEqual(selected["threshold"], 0.5)

    def test_threshold_selection_returns_diagnostics_when_gate_fails(self):
        weak_rankings = [[dict(self.rankings[0][0], score=0.2)], []]
        selected, results = choose_threshold(self.examples, weak_rankings)
        self.assertIsNone(selected)
        self.assertEqual(len(results), 5)


if __name__ == "__main__":
    unittest.main()
