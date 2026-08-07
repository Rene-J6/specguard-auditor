import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.ingest_rag import (
    PageText,
    _split_long_text,
    build_source_chunks,
    parse_pages,
    prepare_documents,
    remove_repeated_margins,
)


class RagIngestionTests(unittest.TestCase):
    def test_numbered_parser_supports_inline_and_split_headings(self):
        sections = parse_pages([
            PageText(1, "4.2 Product quality model\nIntroductory text."),
            PageText(2, "4.2.1\nfunctional suitability\nProvides needed functions."),
        ], "numbered")

        self.assertEqual([item["clause"] for item in sections], ["4.2", "4.2.1"])
        self.assertEqual(sections[1]["title"], "functional suitability")
        self.assertEqual(sections[1]["page"], 2)

    def test_section_parser_and_page_fallback_preserve_order(self):
        sections = parse_pages([
            PageText(3, "STRATEGIC THRUSTS\nFirst paragraph.\nDIGITAL TALENT\nSecond paragraph.")
        ], "section")
        self.assertEqual(
            [item["title"] for item in sections],
            ["STRATEGIC THRUSTS", "DIGITAL TALENT"],
        )

        fallback = parse_pages([PageText(7, "plain sentence ending here.")], "numbered")
        self.assertEqual(fallback[0]["title"], "Page 7")

    def test_repeated_headers_and_footers_are_removed(self):
        pages = [PageText(index, f"COMMON HEADER\nBody {index}.\nCOMMON FOOTER")
                 for index in range(1, 5)]
        cleaned = remove_repeated_margins(pages)
        self.assertEqual([item.text for item in cleaned], [f"Body {i}." for i in range(1, 5)])

    def test_long_clause_repeats_parent_heading(self):
        parts = _split_long_text("5.2.5 Quality", ["One sentence. " * 20], max_chars=80)
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(part.startswith("5.2.5 Quality\n") for part in parts))
        self.assertTrue(all(len(part) <= 80 for part in parts))

    def test_chunk_ids_and_metadata_are_deterministic(self):
        source = {"filename": "sample.pdf", "standard": "Sample Standard",
                  "parser": "numbered"}
        pages = [PageText(1, "1 Scope\nThe system context is defined here.")]
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "sample.pdf"
            path.write_bytes(b"same source")
            with patch("scripts.ingest_rag.extract_pages", return_value=pages):
                first_docs, first_ids, _ = build_source_chunks(path, source)
                second_docs, second_ids, _ = build_source_chunks(path, source)

        self.assertEqual(first_ids, second_ids)
        self.assertEqual(first_docs[0].metadata["page"], 1)
        self.assertEqual(first_docs[0].metadata["standard"], "Sample Standard")
        self.assertEqual(first_docs[0].metadata["part_count"], 1)

    def test_prepare_documents_removes_exact_duplicate_ids(self):
        document = type("FakeDocument", (), {})()
        source = {"filename": "sample.pdf", "standard": "Sample", "parser": "numbered"}
        with patch("scripts.ingest_rag.load_source_manifest", return_value=[source]), \
                patch("scripts.ingest_rag.build_source_chunks",
                      return_value=([document, document], ["same", "same"], "hash")):
            documents, ids, details = prepare_documents("ignored.json")

        self.assertEqual(documents, [document])
        self.assertEqual(ids, ["same"])
        self.assertEqual(details[0]["exact_duplicates_removed"], 1)


if __name__ == "__main__":
    unittest.main()
