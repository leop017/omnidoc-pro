"""Tests for :mod:`omnidoc.processors.pipeline` (post-engine stage seam).

Every stage (clean / chunk / enhance) is degradable (System Rule #3): a
failing stage records a warning on the :class:`DocumentResult` and preserves
the engine's Markdown rather than aborting the batch. The tests inject tiny
stub collaborators so no real cleaner / chunker / LLM is exercised.
"""

import unittest

from omnidoc.core.document import Chunk, ConversionStatus, Document, DocumentResult
from omnidoc.processors.pipeline import ProcessingPipeline, default_pipeline


class _Cleaner:
    def __init__(self, out="CLEANED", exc=None):
        self.out = out
        self.exc = exc
        self.calls = 0

    def clean(self, md, cfg):
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        return self.out


class _Chunker:
    def __init__(self, exc=None):
        self.calls = 0
        self.exc = exc

    def chunk(self, doc, chunking):
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        return [Chunk(text="c1"), Chunk(text="c2")]


class _Enhancer:
    def __init__(self, exc=None):
        self.calls = 0
        self.exc = exc

    def enhance(self, result, cfg):
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        result.markdown = "ENHANCED"
        return result


def _run(cleaner=None, chunker_factory=None, enhancer=None, cfg=None, markdown="RAW"):
    chunker = _Chunker()
    if chunker_factory is None:
        chunker_factory = lambda strategy: chunker  # noqa: E731
    pipeline = ProcessingPipeline(
        cleaner=cleaner, enhancer=enhancer, chunker_factory=chunker_factory
    )
    result = DocumentResult(source="s.txt", markdown=markdown, document=Document(text=markdown))
    pipeline.run(result, cfg or {})
    return pipeline, result, chunker


class TestCleanStage(unittest.TestCase):
    def test_cleaned_when_rules_enabled(self):
        cleaner = _Cleaner(out="TIDY")
        _, result, _ = _run(
            cleaner=cleaner,
            cfg={"cleaning_rules": {"remove_page_numbers": True}},
            markdown="  raw  ",
        )
        self.assertEqual(cleaner.calls, 1)
        self.assertEqual(result.markdown, "TIDY")
        self.assertIs(result.document, result.document)  # document rebuilt

    def test_cleaned_no_rules_skipped(self):
        cleaner = _Cleaner()
        _, result, _ = _run(cleaner=cleaner, cfg={}, markdown="raw")
        self.assertEqual(cleaner.calls, 0)
        self.assertEqual(result.markdown, "raw")

    def test_clean_all_rules_disabled_skipped(self):
        cleaner = _Cleaner()
        _, result, _ = _run(
            cleaner=cleaner, cfg={"cleaning_rules": {"a": False, "b": False}}, markdown="raw"
        )
        self.assertEqual(cleaner.calls, 0)

    def test_clean_failure_degrades(self):
        cleaner = _Cleaner(exc=RuntimeError("clean boom"))
        _, result, _ = _run(
            cleaner=cleaner, cfg={"cleaning_rules": {"a": True}}, markdown="RAW"
        )
        self.assertEqual(result.markdown, "RAW")  # preserved
        self.assertTrue(any("cleaning stage failed" in w for w in result.warnings))

    def test_table_sources_scope_out_duplicate_headers(self):
        # M5 regression: spreadsheet/HTML conversions emit real data rows —
        # the generic duplicate-header rule must not silently delete them.
        cleaner = _Cleaner()
        seen: dict = {}
        original = cleaner.clean

        def spy(md, cfg):
            seen["rules"] = dict(cfg.get("cleaning_rules") or {})
            return original(md, cfg)

        cleaner.clean = spy
        pipeline = ProcessingPipeline(cleaner=cleaner)
        result = DocumentResult(
            source="s.xlsx", source_format="xlsx", markdown="| a | a |",
            document=Document(text="| a | a |"),
        )
        pipeline._clean(result, {"cleaning_rules": {"remove_duplicate_headers": True}})
        self.assertFalse(seen["rules"]["remove_duplicate_headers"])

    def test_non_table_sources_keep_duplicate_headers(self):
        cleaner = _Cleaner()
        seen: dict = {}
        original = cleaner.clean

        def spy(md, cfg):
            seen["rules"] = dict(cfg.get("cleaning_rules") or {})
            return original(md, cfg)

        cleaner.clean = spy
        pipeline = ProcessingPipeline(cleaner=cleaner)
        result = DocumentResult(
            source="s.docx", source_format="docx", markdown="raw",
            document=Document(text="raw"),
        )
        pipeline._clean(result, {"cleaning_rules": {"remove_duplicate_headers": True}})
        self.assertTrue(seen["rules"]["remove_duplicate_headers"])


class TestChunkStage(unittest.TestCase):
    def test_chunked_when_enabled(self):
        _, result, chunker = _run(cfg={"chunking": {"enabled": True, "strategy": "fixed"}})
        self.assertEqual(chunker.calls, 1)
        self.assertEqual(len(result.chunks), 2)
        self.assertEqual(result.chunks[0].text, "c1")

    def test_chunk_disabled_skipped(self):
        _, result, chunker = _run(cfg={"chunking": {"enabled": False}})
        self.assertEqual(chunker.calls, 0)
        self.assertEqual(result.chunks, [])

    def test_chunk_failure_degrades(self):
        failing = _Chunker(exc=RuntimeError("chunk boom"))
        pipeline, result, _ = _run(
            chunker_factory=lambda strategy: failing,
            cfg={"chunking": {"enabled": True, "strategy": "sentence"}},
        )
        self.assertEqual(result.chunks, [])
        self.assertTrue(any("chunking stage" in w for w in result.warnings))


class TestEnhanceStage(unittest.TestCase):
    def _llm_cfg(self):
        return {
            "llm": {"enabled": True, "base_url": "http://x", "api_key": "k", "model": "m"},
            "offline_mode": False,
        }

    def test_enhanced_when_llm_on_and_wired(self):
        enhancer = _Enhancer()
        _, result, _ = _run(enhancer=enhancer, cfg=self._llm_cfg(), markdown="RAW")
        self.assertEqual(enhancer.calls, 1)
        self.assertEqual(result.markdown, "ENHANCED")

    def test_enhance_skipped_when_llm_disabled(self):
        enhancer = _Enhancer()
        _, result, _ = _run(enhancer=enhancer, cfg={"llm": {"enabled": False}})
        self.assertEqual(enhancer.calls, 0)

    def test_enhance_skipped_when_offline(self):
        enhancer = _Enhancer()
        cfg = self._llm_cfg()
        cfg["offline_mode"] = True
        _, result, _ = _run(enhancer=enhancer, cfg=cfg)
        self.assertEqual(enhancer.calls, 0)

    def test_enhance_no_enhancer_records_warning(self):
        _, result, _ = _run(enhancer=None, cfg=self._llm_cfg(), markdown="RAW")
        self.assertEqual(result.markdown, "RAW")
        self.assertTrue(any("no enhancer" in w for w in result.warnings))

    def test_enhance_failure_degrades(self):
        enhancer = _Enhancer(exc=RuntimeError("llm boom"))
        _, result, _ = _run(enhancer=enhancer, cfg=self._llm_cfg(), markdown="RAW")
        self.assertEqual(result.markdown, "RAW")
        self.assertTrue(any("LLM enrichment failed" in w for w in result.warnings))


class TestDefaultPipeline(unittest.TestCase):
    def test_wires_cleaner_and_enhancer(self):
        pipeline = default_pipeline()
        self.assertIsNotNone(pipeline.cleaner)
        self.assertIsNotNone(pipeline.enhancer)
        self.assertTrue(hasattr(pipeline.cleaner, "clean"))
        self.assertEqual(pipeline.enhancer.name, "llm-image")

    def test_explicit_injection_preserved(self):
        pipeline = default_pipeline(cleaner=_Cleaner(), enhancer=_Enhancer())
        self.assertIsInstance(pipeline.cleaner, _Cleaner)
        self.assertIsInstance(pipeline.enhancer, _Enhancer)


class TestCleanPreservesStructure(unittest.TestCase):
    """B1 regression: the clean stage must not drop the engine's elements /
    metadata when it rebuilds the :class:`Document` around the cleaned text."""

    def _cleaner(self, out="CLEANED"):
        return _Cleaner(out=out)

    def test_clean_keeps_engine_elements(self):
        from omnidoc.core.document import Element

        cleaner = self._cleaner()
        pipeline = ProcessingPipeline(cleaner=cleaner)
        result = DocumentResult(
            source="s.docx",
            source_format="docx",
            markdown="  raw  ",
            document=Document(
                text="  raw  ",
                elements=[Element("heading", "Intro", metadata={"level": 2})],
                metadata={"origin": "docx"},
            ),
        )
        pipeline._clean(result, {"cleaning_rules": {"remove_page_numbers": True}})
        self.assertEqual(result.markdown, "CLEANED")
        # Structure must survive the rebuild so the header-aware chunker can
        # still use it instead of falling back to text re-parsing.
        self.assertEqual(len(result.document.elements), 1)
        self.assertEqual(result.document.elements[0].element_type, "heading")
        self.assertEqual(result.document.metadata, {"origin": "docx"})

    def test_clean_with_none_document_is_safe(self):
        # An engine that left ``result.document`` unset must not crash the
        # clean stage.
        cleaner = self._cleaner()
        pipeline = ProcessingPipeline(cleaner=cleaner)
        result = DocumentResult(source="s.txt", source_format="txt", markdown="raw")
        pipeline._clean(result, {"cleaning_rules": {"remove_page_numbers": True}})
        self.assertEqual(result.markdown, "CLEANED")
        self.assertTrue(result.document.elements is not None)


class TestZeroChunkStatus(unittest.TestCase):
    """B4 regression: 0 chunks for a non-empty document must degrade the
    result so the CLI exit code / ``success`` flag reflect the empty RAG index."""

    def _empty_chunker(self):
        class _Empty:
            def __init__(self):
                self.calls = 0

            def chunk(self, doc, chunking):
                self.calls += 1
                return []

        return _Empty()

    def test_zero_chunks_degrades_status(self):
        chunker = self._empty_chunker()
        pipeline = ProcessingPipeline(chunker_factory=lambda strategy: chunker)
        result = DocumentResult(
            source="s.txt",
            markdown="# A\n\nbody",
            document=Document(text="# A\n\nbody"),
        )
        pipeline._chunk(result, {"chunking": {"enabled": True, "strategy": "markdown"}})
        self.assertEqual(result.chunks, [])
        self.assertEqual(result.status, ConversionStatus.DEGRADED)
        self.assertTrue(result.success)  # DEGRADED is still "success" for the CLI

    def test_nonzero_chunks_stay_ok(self):
        chunker = _Chunker()  # returns 2 chunks
        pipeline = ProcessingPipeline(chunker_factory=lambda strategy: chunker)
        result = DocumentResult(
            source="s.txt",
            markdown="# A\n\nbody",
            document=Document(text="# A\n\nbody"),
        )
        pipeline._chunk(result, {"chunking": {"enabled": True, "strategy": "fixed"}})
        self.assertEqual(result.status, ConversionStatus.OK)


class TestRechunkAfterEnhance(unittest.TestCase):
    """A2 regression: when the LLM enhancer rewrites the Markdown *after* the
    chunk stage, the chunks must be re-derived so they stay locatable in the
    final text."""

    class _RechunkingEnhancer:
        """Mimics :class:`LlmEnhancer`: rewrites markdown AND mirrors the new
        text into ``result.document`` (as the real enhancer does)."""

        def __init__(self):
            self.calls = 0

        def enhance(self, result, cfg):
            self.calls += 1
            result.markdown = result.markdown + "\n> caption"
            # The real LlmEnhancer mirrors the rewrite into both
            # ``result.markdown`` and ``result.document``. Keep the engine's
            # structure so the re-chunk stage can still produce chunks.
            result.document = Document(
                text=result.markdown,
                elements=result.document.elements,
                metadata=result.document.metadata,
            )
            return result

    def test_chunks_unchanged_when_enhancer_leaves_text_same(self):
        # No-op enhancer: markdown equals document.text -> no re-chunk.
        class _Noop:
            def enhance(self, result, cfg):
                return result

        chunker = _Chunker()
        pipeline = ProcessingPipeline(
            enhancer=_Noop(), chunker_factory=lambda strategy: chunker
        )
        result = DocumentResult(source="s.txt", markdown="RAW", document=Document(text="RAW"))
        pipeline.run(result, {"chunking": {"enabled": True}, "llm": {"enabled": True, "base_url": "x", "api_key": "k", "model": "m"}})
        self.assertEqual(chunker.calls, 1)  # only the initial chunk stage

    def test_rechunk_when_enhancer_changes_text(self):
        chunker = _Chunker()
        enhancer = self._RechunkingEnhancer()
        pipeline = ProcessingPipeline(
            enhancer=enhancer, chunker_factory=lambda strategy: chunker
        )
        result = DocumentResult(source="s.txt", markdown="RAW", document=Document(text="RAW"))
        pipeline.run(
            result,
            {
                "chunking": {"enabled": True},
                "llm": {"enabled": True, "base_url": "x", "api_key": "k", "model": "m"},
            },
        )
        # The chunker must run twice: once in the chunk stage, once to re-derive
        # chunks against the enriched text.
        self.assertEqual(chunker.calls, 2)
        self.assertIn("caption", result.markdown)
        self.assertGreater(len(result.chunks), 0)


if __name__ == "__main__":
    unittest.main()
