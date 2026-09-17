"""Tests for :mod:`omnidoc.processors.pipeline` (post-engine stage seam).

Every stage (clean / chunk / enhance) is degradable (System Rule #3): a
failing stage records a warning on the :class:`DocumentResult` and preserves
the engine's Markdown rather than aborting the batch. The tests inject tiny
stub collaborators so no real cleaner / chunker / LLM is exercised.
"""

import unittest

from omnidoc.core.document import Chunk, Document, DocumentResult
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


if __name__ == "__main__":
    unittest.main()
