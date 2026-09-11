"""Post-processing pipeline: cleaner → chunker → (optional) LLM enhancer.

This is the core post-processing seam (System Rule #2: no UI imports). Each
stage degrades gracefully (System Rule #3) so a single failing stage never
aborts a batch — it records a warning on the :class:`DocumentResult` and keeps
whatever Markdown the engine already produced.
"""

from __future__ import annotations

from typing import Any, Optional

from omnidoc.core.document import Document, DocumentResult
from omnidoc.core.interfaces import (
    ChunkerInterface,
    CleanerInterface,
    EnhancerInterface,
)
from omnidoc.processors.chunkers import get_chunker


class ProcessingPipeline:
    """Runs the post-engine stages against a :class:`DocumentResult` in place.

    Stages (all optional / degradable):

    * **clean** — :class:`CleanerInterface` (page numbers / duplicate headers /
      whitespace). Skipped when ``cleaning_rules`` is absent or all rules are
      disabled.
    * **chunk** — a :class:`ChunkerInterface` chosen by
      ``chunking.strategy``. Skipped unless ``chunking.enabled``.
    * **enhance** — an :class:`EnhancerInterface` (LLM image description).
      Skipped when the LLM is not enabled, ``offline_mode`` is set, or no
      enhancer is wired in (recorded as a warning, not a failure).
    """

    def __init__(
        self,
        cleaner: Optional[CleanerInterface] = None,
        enhancer: Optional[EnhancerInterface] = None,
        chunker_factory=get_chunker,
    ):
        self.cleaner = cleaner
        self.enhancer = enhancer
        self.chunker_factory = chunker_factory

    def run(
        self,
        result: DocumentResult,
        config: dict[str, Any],
    ) -> DocumentResult:
        """Apply the enabled stages to ``result`` and return it (mutated)."""
        self._clean(result, config)
        self._chunk(result, config)
        self._enhance(result, config)
        return result

    # ── individual stages ──────────────────────────────────────

    def _clean(self, result: DocumentResult, config: dict[str, Any]) -> None:
        if self.cleaner is None:
            return
        rules = config.get("cleaning_rules")
        if not rules or not any(rules.values()):
            return
        if not result.markdown:
            return
        try:
            cleaned = self.cleaner.clean(result.markdown, config)
            result.markdown = cleaned
            result.document = Document(text=cleaned)
        except Exception as e:  # noqa: BLE001 - degrade, never abort the batch
            result.add_warning(f"cleaning stage failed: {e}")

    def _chunk(self, result: DocumentResult, config: dict[str, Any]) -> None:
        chunking = config.get("chunking") or {}
        if not chunking.get("enabled"):
            return
        strategy = chunking.get("strategy", "fixed")
        try:
            chunker: ChunkerInterface = self.chunker_factory(strategy)
            result.chunks = chunker.chunk(result.document, dict(chunking))
        except Exception as e:  # noqa: BLE001
            result.add_warning(f"chunking stage ({strategy}) failed: {e}")

    def _enhance(self, result: DocumentResult, config: dict[str, Any]) -> None:
        llm = config.get("llm") or {}
        offline = bool(config.get("offline_mode", False))
        if not llm.get("enabled") or offline:
            return
        if self.enhancer is None:
            result.add_warning("LLM enabled but no enhancer wired in; skipping enrichment")
            return
        try:
            result = self.enhancer.enhance(result, config)
        except Exception as e:  # noqa: BLE001 - LLM is optional enrichment
            result.add_warning(f"LLM enrichment failed: {e}")


def default_pipeline(
    cleaner: Optional[CleanerInterface] = None,
    enhancer: Optional[EnhancerInterface] = None,
) -> ProcessingPipeline:
    """Pipeline pre-wired with the default Word/Markdown cleaner + LLM enhancer.

    The LLM enhancer is a no-op (records a warning) unless the run config has
    the LLM enabled and ``offline_mode`` is off, so wiring it in is always safe.
    """
    if cleaner is None:
        from omnidoc.processors.cleaners.word_md import WordMdCleaner

        cleaner = WordMdCleaner()
    if enhancer is None:
        from omnidoc.processors.enhancers import get_enhancer

        enhancer = get_enhancer()
    return ProcessingPipeline(cleaner=cleaner, enhancer=enhancer)
