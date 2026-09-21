"""Tests for :mod:`omnidoc.controller.conversion` (the orchestration core).

The controller's behaviour is driven by two injected collaborators — an
:class:`EngineRouter` (which we build from tiny stub engines) and a
:class:`ProcessingPipeline` (stubbed here so the tests never touch the real
cleaner / chunker / LLM). This pins down the graceful-degradation contract
(System Rule #3): fallback ordering, ``allow_fallback`` truncation, the
``DEGRADED`` / ``ERROR`` status markers, and the "one bad file never aborts a
batch" guarantee.
"""

import unittest

from omnidoc.controller.conversion import ConversionController, _to_config_dict
from omnidoc.controller.router import EngineRouter
from omnidoc.core.config import OmniDocConfig
from omnidoc.core.document import ConversionStatus, DocumentResult


class _Engine:
    """Minimal engine stub: controllable availability, markdown, or exception."""

    def __init__(self, name, supports, available=True, markdown=None, exc=None):
        self.name = name
        self._supports = supports
        self._available = available
        self._markdown = markdown
        self._exc = exc
        self.calls = 0

    def supports(self, source):
        return self._supports(source)

    def available(self):
        return self._available

    def convert_document(self, source, cfg):
        self.calls += 1
        if self._exc is not None:
            raise self._exc
        return DocumentResult(source=source, engine=self.name, markdown=self._markdown or "")


class _Pipeline:
    def __init__(self):
        self.calls = 0

    def run(self, result, cfg):
        self.calls += 1
        return result


_ALWAYS = lambda s: True  # noqa: E731
_NEVER = lambda s: False  # noqa: E731


def _controller(deep, breadth, pipeline=None):
    router = EngineRouter(deep=deep, breadth=breadth)
    pipeline = pipeline if pipeline is not None else _Pipeline()
    return ConversionController(router=router, pipeline=pipeline), pipeline


class TestSuccessAndFallback(unittest.TestCase):
    def test_first_engine_success_no_fallback(self):
        deep = _Engine("deep", _ALWAYS, markdown="D")
        breadth = _Engine("breadth", _ALWAYS, markdown="B")
        ctrl, _ = _controller(deep, breadth)
        res = ctrl.convert("x.docx", {})
        self.assertIs(res.status, ConversionStatus.OK)
        self.assertFalse(res.fallback_used)
        self.assertEqual(res.markdown, "D")
        self.assertEqual(res.engine, "deep")
        self.assertEqual(breadth.calls, 0)

    def test_second_engine_fallback_marks_degraded(self):
        deep = _Engine("deep", _ALWAYS, exc=RuntimeError("boom"))
        breadth = _Engine("breadth", _ALWAYS, markdown="B")
        ctrl, _ = _controller(deep, breadth)
        res = ctrl.convert("x.docx", {})
        self.assertIs(res.status, ConversionStatus.DEGRADED)
        self.assertTrue(res.fallback_used)
        self.assertEqual(res.markdown, "B")
        self.assertIn("fell back", res.warnings[-1])

    def test_unavailable_first_engine_is_skipped(self):
        deep = _Engine("deep", _ALWAYS, available=False)
        breadth = _Engine("breadth", _ALWAYS, markdown="B")
        ctrl, _ = _controller(deep, breadth)
        res = ctrl.convert("x.docx", {})
        self.assertIs(res.status, ConversionStatus.DEGRADED)
        self.assertTrue(res.fallback_used)
        self.assertEqual(breadth.calls, 1)
        self.assertIn("fell back", res.warnings[-1])

    def test_all_engines_fail_returns_last_error(self):
        deep = _Engine("deep", _ALWAYS, exc=ValueError("d"))
        breadth = _Engine("breadth", _ALWAYS, exc=RuntimeError("b"))
        ctrl, _ = _controller(deep, breadth)
        res = ctrl.convert("x.docx", {})
        self.assertIs(res.status, ConversionStatus.ERROR)
        self.assertFalse(res.success)
        self.assertEqual(res.engine, "breadth")  # the last one tried
        self.assertTrue(res.errors)
        self.assertIn("RuntimeError", res.errors[-1])


class TestAllowFallbackTruncation(unittest.TestCase):
    def test_allow_fallback_false_uses_first_engine_only(self):
        deep = _Engine("deep", _ALWAYS, exc=RuntimeError("boom"))
        breadth = _Engine("breadth", _ALWAYS, markdown="B")
        ctrl, _ = _controller(deep, breadth)
        res = ctrl.convert("x.docx", {"allow_fallback": False})
        self.assertIs(res.status, ConversionStatus.ERROR)
        self.assertFalse(res.fallback_used)
        self.assertEqual(deep.calls, 1)
        self.assertEqual(breadth.calls, 0)  # never reached

    def test_allow_fallback_false_success_stays_ok(self):
        deep = _Engine("deep", _ALWAYS, markdown="D")
        breadth = _Engine("breadth", _ALWAYS, markdown="B")
        ctrl, _ = _controller(deep, breadth)
        res = ctrl.convert("x.docx", {"allow_fallback": False})
        self.assertIs(res.status, ConversionStatus.OK)
        self.assertFalse(res.fallback_used)
        self.assertEqual(breadth.calls, 0)


class TestBatchIsolation(unittest.TestCase):
    def test_one_bad_source_does_not_abort_batch(self):
        class _MixedEngine:
            name = "deep"

            def supports(self, source):
                return source != "bad.pdf"

            def available(self):
                return True

            def convert_document(self, source, cfg):
                return DocumentResult(source=source, engine=self.name, markdown="OK")

        # breadth always claims but always fails, so "bad.pdf" ends up ERROR.
        breadth = _Engine("breadth", _ALWAYS, exc=RuntimeError("nope"))
        ctrl, _ = _controller(_MixedEngine(), breadth)

        results = ctrl.convert_batch(["good.pdf", "bad.pdf"], {})
        self.assertEqual(len(results), 2)
        self.assertTrue(results[0].success)  # good.pdf handled by deep
        self.assertIs(results[1].status, ConversionStatus.ERROR)  # bad.pdf -> breadth raised


class TestPipelineAndElapsed(unittest.TestCase):
    def test_convert_runs_pipeline_and_sets_elapsed(self):
        deep = _Engine("deep", _ALWAYS, markdown="D")
        breadth = _Engine("breadth", _NEVER)
        pipeline = _Pipeline()
        ctrl, _ = _controller(deep, breadth, pipeline)
        res = ctrl.convert("x.docx", {})
        self.assertEqual(pipeline.calls, 1)
        self.assertGreaterEqual(res.elapsed, 0.0)
        self.assertIs(res, res)


class TestToConfigDict(unittest.TestCase):
    def test_none_becomes_default_engine_kwargs(self):
        cfg = _to_config_dict(None)
        self.assertIsInstance(cfg, dict)
        # routing flags are always present so UI checkboxes take effect
        self.assertIn("deep_first", cfg)
        self.assertIn("allow_fallback", cfg)

    def test_dict_is_copied(self):
        src = {"chunking": {"enabled": True}}
        cfg = _to_config_dict(src)
        self.assertIsNot(cfg, src)
        self.assertEqual(cfg["chunking"]["enabled"], True)

    def test_config_object_uses_to_engine_kwargs(self):
        o = OmniDocConfig(deep_first=False, allow_fallback=False)
        cfg = _to_config_dict(o)
        self.assertEqual(cfg["deep_first"], False)
        self.assertEqual(cfg["allow_fallback"], False)


if __name__ == "__main__":
    unittest.main()
