import unittest

from langchain_core.documents import Document

from app.retrieval import retrieve_standard_evidence


class FakeStore:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def similarity_search_with_score(self, query, k):
        self.calls.append((query, k))
        return self.rows[:k]


class RagRetrievalTests(unittest.TestCase):
    def test_top_k_scores_metadata_and_order_are_preserved(self):
        rows = [
            (Document(page_content="second", metadata={"source": "b.pdf"}), 0.4),
            (Document(page_content="first", metadata={
                "standard": "ISO", "clause": "1.2", "title": "Scope",
                "source": "folder/a.pdf", "page": 3,
            }), 0.2),
        ]
        store = FakeStore(rows)
        result = retrieve_standard_evidence(store, "query", k=5, threshold=0.5)

        self.assertEqual(store.calls, [("query", 5)])
        self.assertEqual([item["text"] for item in result["candidates"]], ["first", "second"])
        self.assertAlmostEqual(result["selected_clause"]["score"], 0.8)
        self.assertEqual(result["selected_clause"]["source"], "a.pdf")

    def test_threshold_filters_and_returns_explicit_no_result(self):
        store = FakeStore([(Document(page_content="weak"), 0.51)])
        result = retrieve_standard_evidence(store, "query", threshold=0.5)
        self.assertIsNone(result["selected_clause"])
        self.assertEqual(result["candidates"], [])

    def test_no_threshold_keeps_fixed_top_k_candidates(self):
        store = FakeStore([(Document(page_content="weak"), 0.9)])
        result = retrieve_standard_evidence(store, "query")
        self.assertEqual(result["selected_clause"]["text"], "weak")


if __name__ == "__main__":
    unittest.main()
