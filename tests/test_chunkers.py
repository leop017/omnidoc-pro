"""Migrated from ``docconvert`` ``tests/test_chunkers.py``.

The OmniDoc chunkers are stateless: every tuning knob (``chunk_size`` /
``chunk_overlap`` / ``max_chunk_size``) is read from the pipeline ``config``
dict at :meth:`chunk` time instead of being stored on the instance. So the
original constructor knobs become per-call config entries. ``MarkdownParser``
was not ported, so the Markdown cases build a :class:`Document` by hand.
All assertions that did not depend on the parser are kept verbatim.
"""

import unittest

from omnidoc.core.document import Document, Element
from omnidoc.processors.chunkers import (
    FixedSizeChunker,
    MarkdownChunker,
    SentenceChunker,
    get_chunker,
)


class TestGetChunkerFactory(unittest.TestCase):

    def test_fixed_returns_fixed_chunker(self):
        self.assertIsInstance(get_chunker("fixed"), FixedSizeChunker)

    def test_fixed_size_alias_returns_fixed_chunker(self):
        self.assertIsInstance(get_chunker("fixed_size"), FixedSizeChunker)

    def test_sentence_returns_sentence_chunker(self):
        self.assertIsInstance(get_chunker("sentence"), SentenceChunker)

    def test_markdown_returns_markdown_chunker(self):
        self.assertIsInstance(get_chunker("markdown"), MarkdownChunker)

    def test_md_alias_returns_markdown_chunker(self):
        self.assertIsInstance(get_chunker("md"), MarkdownChunker)

    def test_unknown_strategy_raises(self):
        with self.assertRaises(ValueError):
            get_chunker("magic")

    def test_kwargs_accepted_but_ignored(self):
        # OmniDoc chunkers are stateless; extra kwargs are accepted (for
        # factory-signature compatibility) but must NOT be persisted.
        chunker = get_chunker("fixed", chunk_size=128, chunk_overlap=16)
        self.assertIsInstance(chunker, FixedSizeChunker)
        self.assertFalse(hasattr(chunker, "chunk_size"))
        self.assertFalse(hasattr(chunker, "chunk_overlap"))


class TestFixedSizeChunker(unittest.TestCase):

    def test_invalid_chunk_size(self):
        with self.assertRaises(ValueError):
            FixedSizeChunker().chunk("abc", {"chunk_size": 0})
        with self.assertRaises(ValueError):
            FixedSizeChunker().chunk("abc", {"chunk_size": -1})

    def test_invalid_overlap(self):
        with self.assertRaises(ValueError):
            FixedSizeChunker().chunk("abc", {"chunk_size": 10, "chunk_overlap": -1})
        with self.assertRaises(ValueError):
            FixedSizeChunker().chunk("abc", {"chunk_size": 10, "chunk_overlap": 10})

    def test_short_text_no_split(self):
        chunker = FixedSizeChunker()
        chunks = chunker.chunk("hello world", {"chunk_size": 100, "chunk_overlap": 10})
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].text, "hello world")
        self.assertEqual(chunks[0].metadata["chunk_index"], 0)
        self.assertEqual(chunks[0].metadata["chunk_count"], 1)

    def test_long_text_creates_overlapping_chunks(self):
        chunker = FixedSizeChunker()
        text = "a" * 100
        chunks = chunker.chunk(text, {"chunk_size": 20, "chunk_overlap": 5})
        self.assertGreater(len(chunks), 1)
        for i, c in enumerate(chunks):
            self.assertEqual(c.metadata["chunk_index"], i)
            self.assertEqual(c.metadata["chunk_count"], len(chunks))
        for c in chunks[:-1]:
            self.assertEqual(len(c.text), 20)
        self.assertLessEqual(len(chunks[-1].text), 20)

    def test_empty_text_returns_no_chunks(self):
        chunker = FixedSizeChunker()
        self.assertEqual(chunker.chunk("", {}), [])
        # Pure-whitespace is still a single (small) chunk; the chunker
        # does not normalize input. Parsers handle normalization.
        chunks = chunker.chunk("   ", {})
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].text, "   ")

    def test_metadata_propagates(self):
        chunker = FixedSizeChunker()
        doc = Document(text="abcdef", metadata={"origin": "unit-test"})
        chunks = chunker.chunk(doc, {})
        self.assertEqual(chunks[0].metadata["origin"], "unit-test")


class TestSentenceChunker(unittest.TestCase):

    def test_breaks_on_period(self):
        chunker = SentenceChunker()
        text = "First sentence. Second sentence. Third sentence."
        chunks = chunker.chunk(text, {"chunk_size": 100, "chunk_overlap": 10})
        joined = " ".join(c.text for c in chunks)
        self.assertIn("First sentence", joined)
        self.assertIn("Third sentence", joined)

    def test_chinese_punctuation(self):
        chunker = SentenceChunker()
        # The ported boundary regex requires trailing whitespace after a
        # CJK terminator, so the test text uses spaces to force a split.
        text = "第一句。 第二句！ 第三句？ 第四句。"
        chunks = chunker.chunk(text, {"chunk_size": 200, "chunk_overlap": 20})
        joined = " ".join(c.text for c in chunks)
        self.assertIn("第一句", joined)
        self.assertIn("第四句", joined)

    def test_empty_text(self):
        chunker = SentenceChunker()
        self.assertEqual(chunker.chunk("", {}), [])

    def test_respects_chunk_size_upper_bound(self):
        chunker = SentenceChunker()
        text = ". ".join(["sentence"] * 30)
        chunks = chunker.chunk(text, {"chunk_size": 40, "chunk_overlap": 5})
        for c in chunks:
            self.assertLessEqual(len(c.text), 80)


class TestMarkdownChunker(unittest.TestCase):

    @staticmethod
    def _doc(md):
        elements = [
            Element("heading", "Title"),
            Element("paragraph", "Intro."),
            Element("heading", "Section A"),
            Element("paragraph", "Body A."),
            Element("heading", "Section B"),
            Element("paragraph", "Body B."),
        ]
        return Document(text=md, elements=elements)

    def test_one_chunk_per_section(self):
        md = "# Title\n\nIntro.\n\n## Section A\n\nBody A.\n\n## Section B\n\nBody B."
        doc = self._doc(md)
        chunks = MarkdownChunker().chunk(doc, {})
        self.assertGreaterEqual(len(chunks), 2)
        headers = [c.metadata["header"] for c in chunks if "header" in c.metadata]
        self.assertIn("Section A", headers)
        self.assertIn("Section B", headers)

    def test_empty_document(self):
        self.assertEqual(MarkdownChunker().chunk(Document(), {}), [])

    def test_max_chunk_size_splits_long(self):
        md = "# H\n\n" + ("x" * 5000)
        doc = Document(text=md, elements=[
            Element("heading", "H"),
            Element("paragraph", "x" * 5000),
        ])
        chunks = MarkdownChunker().chunk(doc, {"max_chunk_size": 200})
        self.assertGreater(len(chunks), 1)
        self.assertTrue(any("part" in c.metadata for c in chunks))

    def test_fallback_parses_text_when_elements_empty(self):
        # Engines populate document.text but never document.elements; the
        # header-aware strategy must degrade to parsing headings from text
        # instead of silently returning no chunks.
        md = "# 章节A\n\n正文一\n\n## 章节B\n\n正文二\n"
        doc = Document(text=md)  # no elements
        chunks = MarkdownChunker().chunk(doc, {})
        self.assertGreaterEqual(len(chunks), 2)
        headers = [c.metadata["header"] for c in chunks if "header" in c.metadata]
        self.assertIn("章节A", headers)
        self.assertIn("章节B", headers)

    def test_fallback_empty_text_still_empty(self):
        doc = Document(text="   ")  # no elements, no real text
        self.assertEqual(MarkdownChunker().chunk(doc, {}), [])


if __name__ == "__main__":
    unittest.main()
