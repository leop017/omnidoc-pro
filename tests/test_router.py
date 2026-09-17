"""Mock tests for :mod:`omnidoc.controller.router` (Phase 5c).

The router's behaviour is fully determined by each engine's
:meth:`supports` / :meth:`available` answers, so we drive it with tiny stub
engines whose answers are controlled per test. This pins down the exact
selection + fallback-chain semantics without pulling in the real engines.
"""

import unittest

from omnidoc.controller.router import EngineRouter, get_router
from omnidoc.engines.deep_engine import DeepEngine
from omnidoc.engines.markitdown_engine import MarkItDownEngine


class _Stub:
    def __init__(self, name, supports_fn, available=True):
        self.name = name
        self._supports = supports_fn
        self._available = available

    def supports(self, source):
        return self._supports(source)

    def available(self):
        return self._available


def _make(ds, bs, deep_avail=True, breadth_avail=True):
    deep = _Stub("deep", ds, deep_avail)
    breadth = _Stub("breadth", bs, breadth_avail)
    return EngineRouter(deep=deep, breadth=breadth), deep, breadth


_ALWAYS = lambda s: True  # noqa: E731
_NEVER = lambda s: False  # noqa: E731


class TestSelect(unittest.TestCase):

    def test_deep_first_picks_deep_when_claims_source(self):
        router, deep, breadth = _make(
            ds=_ALWAYS, bs=_NEVER, deep_avail=True, breadth_avail=True
        )
        self.assertIs(router.select("x.docx", {}), deep)

    def test_deep_first_disabled_skips_deep(self):
        router, deep, breadth = _make(ds=_ALWAYS, bs=_ALWAYS)
        self.assertIs(router.select("x.pdf", {"deep_first": False}), breadth)

    def test_deep_unavailable_falls_to_breadth(self):
        router, deep, breadth = _make(ds=_ALWAYS, bs=_ALWAYS, deep_avail=False)
        self.assertIs(router.select("x", {}), breadth)

    def test_breadth_source_goes_to_breadth(self):
        router, deep, breadth = _make(ds=_NEVER, bs=_ALWAYS)
        self.assertIs(router.select("http://x", {}), breadth)

    def test_last_resort_returns_deep_when_only_deep_claims(self):
        # deep claims the source but is unavailable; breadth does not claim it.
        router, deep, breadth = _make(ds=_ALWAYS, bs=_NEVER, deep_avail=False)
        self.assertIs(router.select("x", {}), deep)

    def test_last_resort_returns_breadth_when_only_breadth_claims(self):
        router, deep, breadth = _make(ds=_NEVER, bs=_ALWAYS, breadth_avail=False)
        self.assertIs(router.select("x", {}), breadth)

    def test_last_resort_defaults_to_breadth_when_neither_claims(self):
        router, deep, breadth = _make(ds=_NEVER, bs=_NEVER)
        self.assertIs(router.select("x", {}), breadth)


class TestFallbackChain(unittest.TestCase):

    def test_depth_source_orders_deep_then_breadth(self):
        router, deep, breadth = _make(ds=_ALWAYS, bs=_ALWAYS)
        self.assertEqual(router.fallback_chain("x.docx", {}), [deep, breadth])

    def test_depth_source_without_breadth_claims(self):
        router, deep, breadth = _make(ds=_ALWAYS, bs=_NEVER)
        self.assertEqual(router.fallback_chain("x.docx", {}), [deep])

    def test_breadth_source_only(self):
        router, deep, breadth = _make(ds=_NEVER, bs=_ALWAYS)
        self.assertEqual(router.fallback_chain("x.pdf", {}), [breadth])

    def test_deep_first_disabled_yields_breadth_only(self):
        router, deep, breadth = _make(ds=_ALWAYS, bs=_ALWAYS)
        self.assertEqual(
            router.fallback_chain("x.docx", {"deep_first": False}), [breadth]
        )

    def test_neither_claims_defaults_to_deep(self):
        router, deep, breadth = _make(ds=_NEVER, bs=_NEVER)
        self.assertEqual(router.fallback_chain("x", {}), [deep])


class TestGetRouter(unittest.TestCase):

    def test_defaults_wire_real_engines(self):
        router = get_router()
        self.assertIsInstance(router, EngineRouter)
        self.assertIsInstance(router.deep, DeepEngine)
        self.assertIsInstance(router.breadth, MarkItDownEngine)

    def test_explicit_injection(self):
        deep, breadth = _Stub("deep", _ALWAYS), _Stub("breadth", _ALWAYS)
        router = get_router(deep=deep, breadth=breadth)
        self.assertIs(router.deep, deep)
        self.assertIs(router.breadth, breadth)


if __name__ == "__main__":
    unittest.main()
