"""Engine router (System Rule #1: breadth + depth routing).

Depth formats (``.doc`` / ``.docx`` / ``.xls`` / ``.xlsx``) go to the Deep
Engine when ``deep_first`` is set and its dependencies are importable;
everything else (breadth formats and URLs) goes to the MarkItDown Engine. The
router also exposes the *degradation chain* the pipeline walks when the first
choice fails — Deep -> MarkItDown — so a single bad file never aborts a batch.
"""

from __future__ import annotations

from typing import Any

from omnidoc.core.interfaces import EngineInterface
from omnidoc.engines.deep_engine import DeepEngine
from omnidoc.engines.markitdown_engine import MarkItDownEngine


class EngineRouter:
    def __init__(
        self,
        deep: EngineInterface = None,
        breadth: EngineInterface = None,
    ):
        self.deep = deep if deep is not None else DeepEngine()
        self.breadth = breadth if breadth is not None else MarkItDownEngine()

    def select(self, source: str, config: dict[str, Any]) -> EngineInterface:
        """Pick the preferred engine for ``source`` under ``config``."""
        if config.get("deep_first", True) and self.deep.supports(source) and self.deep.available():
            return self.deep
        if self.breadth.supports(source) and self.breadth.available():
            return self.breadth
        # Last resort: return whichever claims the source so the caller gets a
        # real, actionable error rather than a silent None.
        return self.deep if self.deep.supports(source) else self.breadth

    def fallback_chain(self, source: str, config: dict[str, Any]) -> list[EngineInterface]:
        """Ordered engine list to try, from most to least preferred.

        Depth formats get Deep Engine first and MarkItDown as the fallback
        (System Rule #3: graceful degradation, never abort the batch).
        """
        chain: list[EngineInterface] = []
        if config.get("deep_first", True) and self.deep.supports(source):
            chain.append(self.deep)
        if self.breadth.supports(source):
            chain.append(self.breadth)
        if not chain:
            chain.append(self.breadth if self.breadth.supports(source) else self.deep)
        return chain


def get_router(
    deep: EngineInterface = None,
    breadth: EngineInterface = None,
) -> EngineRouter:
    return EngineRouter(deep=deep, breadth=breadth)
