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

    def test_fullwidth_terminators_split_with_offsets(self):
        # Regression (H2): the boundary regex used to duplicate the ASCII
        # ``!``/``?`` and miss the fullwidth ``！`` (U+FF01) / ``？``
        # (U+FF1F) terminators, so multi-paragraph CJK text split into half
        # the expected sentences.
        from omnidoc.processors.chunkers.sentence import _split_with_offsets

        text = "第一句。\n\n第二句！\n\n第三句？\n\n第四句。"
        sentences = _split_with_offsets(text)
        self.assertEqual(
            [s.text for s in sentences],
            ["第一句。", "第二句！", "第三句？", "第四句。"],
        )

    def test_fullwidth_multibyte_forces_separate_chunks(self):
        # Chunk-level view of the same regression: with a small chunk_size
        # each fullwidth-terminated sentence must land in its own chunk.
        chunker = SentenceChunker()
        text = "第一句。\n\n第二句！\n\n第三句？\n\n第四句。"
        chunks = chunker.chunk(text, {"chunk_size": 6, "chunk_overlap": 0})
        self.assertEqual(
            [c.text for c in chunks],
            ["第一句。", "第二句！", "第三句？", "第四句。"],
        )

    def test_empty_text(self):
        chunker = SentenceChunker()
        self.assertEqual(chunker.chunk("", {}), [])

    def test_respects_chunk_size_upper_bound(self):
        chunker = SentenceChunker()
        text = ". ".join(["sentence"] * 30)
        chunks = chunker.chunk(text, {"chunk_size": 40, "chunk_overlap": 5})
        for c in chunks:
            self.assertLessEqual(len(c.text), 80)

    def test_offsets_match_source_slice(self):
        # Regression: start_index / end_index must be true byte offsets into
        # the original (stripped) source text, not re-inferred heuristics.
        # Slicing text[start:end] must reproduce chunk.text exactly.
        chunker = SentenceChunker()
        sentences = [f"Number {i} is a fact." for i in range(50)]
        text = " ".join(sentences)
        chunks = chunker.chunk(text, {"chunk_size": 120, "chunk_overlap": 20})
        self.assertGreater(len(chunks), 2)
        for c in chunks:
            self.assertEqual(text[c.start_index : c.end_index], c.text)
            self.assertGreaterEqual(c.end_index, c.start_index)

    def test_offsets_contiguous_with_overlap(self):
        # With overlap > 0, chunk[i+1].start_index may be <= chunk[i].end_index
        # (reusing tail context), but must still satisfy start <= end and the
        # slice must round-trip through the source text.
        chunker = SentenceChunker()
        text = "a b c d e f g h i j k l m n o p q r s t u v w x y z"
        chunks = chunker.chunk(text, {"chunk_size": 10, "chunk_overlap": 4})
        for i, c in enumerate(chunks):
            self.assertEqual(text[c.start_index : c.end_index], c.text)
            if i > 0:
                self.assertLessEqual(c.start_index, chunks[i - 1].end_index)


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

    def test_chunk_count_is_real_total_when_split(self):
        # Regression: when max_chunk_size splits one subtree into N pieces,
        # every emitted chunk's metadata["chunk_count"] must equal the real
        # total number of chunks (len(out)), NOT groups * pieces.
        md = "# H\n\n" + ("x" * 5000)
        doc = Document(text=md, elements=[
            Element("heading", "H"),
            Element("paragraph", "x" * 5000),
        ])
        chunks = MarkdownChunker().chunk(doc, {"max_chunk_size": 200})
        self.assertGreater(len(chunks), 1)
        for c in chunks:
            self.assertEqual(c.metadata["chunk_count"], len(chunks))
            self.assertIn(c.metadata["chunk_index"], range(len(chunks)))

    def test_chunk_count_mixed_split_and_unsplit(self):
        # One subtree is split by max_chunk_size, another is not. The
        # chunk_count metadata must reflect the GLOBAL total across all
        # emitted chunks, so downstream RAG consumers read a single number.
        md = "# A\n\n" + ("a" * 5000) + "\n\n# B\n\nshort."
        doc = Document(text=md, elements=[
            Element("heading", "A"),
            Element("paragraph", "a" * 5000),
            Element("heading", "B"),
            Element("paragraph", "short."),
        ])
        chunks = MarkdownChunker().chunk(doc, {"max_chunk_size": 200})
        # A subtree emits multiple pieces, B emits one; total = pieces(A) + 1.
        self.assertGreater(len(chunks), 2)
        for c in chunks:
            self.assertEqual(c.metadata["chunk_count"], len(chunks))

    def test_offsets_roundtrip_with_indented_content(self):
        # Regression (M1): chunk text with *leading* indentation (indented
        # code blocks / nested lists) must keep its offsets accurate. The old
        # code used a plain .strip() when deriving paragraph elements from
        # text, dropping the indentation so doc.text.find missed the chunk
        # and every later chunk's offsets drifted. Now .rstrip() is used so
        # _render output stays locatable byte-for-byte.
        md = (
            "# 章节A\n\n"
            "    code line 1\n"
            "    code line 2\n\n"
            "## 章节B\n\n"
            "- item one\n"
            "  - nested\n\n"
            "plain text\n"
        )
        doc = Document(text=md)  # engines populate text, never elements
        chunks = MarkdownChunker().chunk(doc, {})
        self.assertGreaterEqual(len(chunks), 2)
        for c in chunks:
            self.assertEqual(md[c.start_index : c.end_index], c.text)
            self.assertGreaterEqual(c.end_index, c.start_index)

    def test_indented_split_offsets_stay_contiguous(self):
        # Regression (M1): a long indented subtree split by max_chunk_size
        # uses the O(k) prefix-sum path; each piece's start/end must still
        # round-trip through the source slice and remain contiguous.
        indented = "    " + ("x" * 200)
        md = "# H\n\n" + indented + "\n\ntail."
        doc = Document(text=md)
        chunks = MarkdownChunker().chunk(doc, {"max_chunk_size": 50})
        self.assertGreater(len(chunks), 1)
        for i, c in enumerate(chunks):
            self.assertEqual(md[c.start_index : c.end_index], c.text)
            if i > 0:
                self.assertLessEqual(c.start_index, chunks[i - 1].end_index)


class TestMakeChunkMetadataCopiesNestedLists(unittest.TestCase):
    """Regression: ``make_chunk`` must NOT leak the Deep Engine's nested
    ``metadata["sheets"]`` list across chunks or back into the source
    ``Document.metadata``.

    ``dict(metadata)`` is a top-level shallow copy, so a nested ``list`` value
    (the per-sheet summary list) would otherwise be *shared* by every chunk and
    by the source Document. An in-place mutation downstream (append / mutate
    one sheet summary) would then contaminate every sibling chunk.
    """

    def _doc_metadata(self):
        return {
            "source": "book.xlsx",
            "sheets": [
                {"sheet": "Full", "rows": 10, "cols": 3},
            ],
        }

    def test_sheets_list_not_shared_across_chunks(self):
        from omnidoc.processors.chunkers import make_chunk

        meta = self._doc_metadata()
        c1 = make_chunk("p1", meta, index=0, total=2, start=0, end=2)
        c2 = make_chunk("p2", meta, index=1, total=2, start=2, end=4)

        self.assertFalse(c1.metadata["sheets"] is c2.metadata["sheets"])

        c1.metadata["sheets"].append({"sheet": "MUTATED", "rows": 0, "cols": 0})
        self.assertNotIn(
            {"sheet": "MUTATED", "rows": 0, "cols": 0},
            c2.metadata["sheets"],
        )

    def test_sheets_list_not_shared_with_source_document(self):
        from omnidoc.processors.chunkers import make_chunk

        meta = self._doc_metadata()
        c1 = make_chunk("p1", meta, index=0, total=1, start=0, end=2)

        # Mutating the chunk's sheets list must not leak back to the source.
        c1.metadata["sheets"].append({"sheet": "MUTATED", "rows": 0, "cols": 0})
        self.assertEqual(meta["sheets"], [{"sheet": "Full", "rows": 10, "cols": 3}])

    def test_non_sheets_keys_still_share_reference(self):
        """Only ``sheets`` is independently copied; other keys keep the
        existing top-level dict copy behaviour (no over-copying)."""
        from omnidoc.processors.chunkers import make_chunk

        shared_inner = {"a": 1}
        meta = {"nested": shared_inner}
        c = make_chunk("p", meta, index=0, total=1, start=0, end=1)
        # Top-level mapping is a fresh dict…
        self.assertIsNot(c.metadata, meta)
        # …but a non-list nested value still shares its reference (documented
        # trade-off of the minimal list-only fix).
        self.assertIs(c.metadata["nested"], shared_inner)


if __name__ == "__main__":
    unittest.main()
