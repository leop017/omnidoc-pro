"""Conversion controller — the single entry point the UI / CLI layer calls.

Ties the :class:`EngineRouter` (breadth + depth routing + degradation chain,
System Rule #1/#3) to the :class:`ProcessingPipeline` (clean → chunk → enhance).
The controller is pure core (System Rule #2: it imports no UI library); Gradio
and the CLI are thin shells around :meth:`ConversionController.convert`.
"""

from __future__ import annotations

import time
from typing import Any

from omnidoc.controller.router import EngineRouter, get_router
from omnidoc.core.config import OmniDocConfig
from omnidoc.core.document import ConversionStatus, DocumentResult
from omnidoc.core.interfaces import EngineInterface
from omnidoc.processors.pipeline import ProcessingPipeline, default_pipeline


def _to_config_dict(config: OmniDocConfig | dict[str, Any] | None) -> dict[str, Any]:
    if config is None:
        return OmniDocConfig.default().to_engine_kwargs()
    if isinstance(config, OmniDocConfig):
        return config.to_engine_kwargs()
    return dict(config)


class ConversionController:
    def __init__(
        self,
        router: EngineRouter | None = None,
        pipeline: ProcessingPipeline | None = None,
    ):
        self.router = router if router is not None else get_router()
        self.pipeline = pipeline if pipeline is not None else default_pipeline()

    # ── single source ───────────────────────────────────────────

    def convert(
        self,
        source: str,
        config: OmniDocConfig | dict[str, Any] | None = None,
    ) -> DocumentResult:
        """Convert one ``source`` (a path or URL) and run the post pipeline."""
        cfg = _to_config_dict(config)
        cfg.setdefault("_used_output_names", set())
        t0 = time.perf_counter()
        result = self._convert_with_fallback(source, cfg)
        result = self.pipeline.run(result, cfg)
        self._sync_written_files(result)
        result.elapsed = time.perf_counter() - t0
        return result

    # ── batch ───────────────────────────────────────────────────

    def convert_batch(
        self,
        sources: list[str],
        config: OmniDocConfig | dict[str, Any] | None = None,
    ) -> list[DocumentResult]:
        """Convert many sources; a single bad file never aborts the batch."""
        cfg = _to_config_dict(config)
        # Batch-scoped registry (shared by reference with the engines and the
        # UI download writers) so two same-stem sources never write the same
        # output file — the second would silently overwrite the first.
        cfg.setdefault("_used_output_names", set())
        return [self._convert_one(s, cfg) for s in sources]

    def _convert_one(
        self, source: str, cfg: dict[str, Any]
    ) -> DocumentResult:
        t0 = time.perf_counter()
        result = self._convert_with_fallback(source, cfg)
        result = self.pipeline.run(result, cfg)
        self._sync_written_files(result)
        result.elapsed = time.perf_counter() - t0
        return result

    @staticmethod
    def _sync_written_files(result: DocumentResult) -> None:
        """Re-write the engine-written ``.md`` file with the cleaned Markdown.

        The deep engine serializes and writes *before* the pipeline runs, so
        its file holds the raw conversion output while the preview shows the
        cleaned content. Writing the cleaned content back keeps the two
        consistent. Format exports (.html/.json) keep the raw serialization.

        Only a *single* ``.md`` output path is synced: it is the whole
        document, so ``result.markdown`` is its exact cleaned content.
        Multi-sheet Excel results carry one file *per sheet* — each holds
        that sheet's serialization while ``result.markdown`` is the join of
        all sheets, so writing it back would overwrite every per-sheet file
        with the full joined content and destroy the sheet-level output.
        Those files keep their (correct) raw content instead.
        """
        if not result.output_paths or not result.markdown:
            return
        from pathlib import Path

        md_paths = [p for p in result.output_paths if Path(p).suffix.lower() == ".md"]
        if len(md_paths) != 1:
            return
        try:
            Path(md_paths[0]).write_text(result.markdown, encoding="utf-8")
        except OSError as e:  # noqa: BLE001 - a locked/read-only file must not abort the batch
            result.add_warning(f"清理后内容回写失败，保留引擎原始文件：{e}")

    # ── engine selection with graceful degradation ─────────────

    def _convert_with_fallback(
        self, source: str, cfg: dict[str, Any]
    ) -> DocumentResult:
        chain: list[EngineInterface] = self.router.fallback_chain(source, cfg)
        if not cfg.get("allow_fallback", True):
            chain = chain[:1]

        last: DocumentResult | None = None
        for idx, engine in enumerate(chain):
            if not engine.available():
                last = DocumentResult(
                    source=source, engine=engine.name, status=ConversionStatus.ERROR
                )
                last.add_warning(f"engine '{engine.name}' unavailable (dependencies not importable)")
                continue
            try:
                result = engine.convert_document(source, cfg)
            except Exception as e:  # noqa: BLE001 - degrade to the next engine
                result = DocumentResult(
                    source=source, engine=engine.name, status=ConversionStatus.ERROR
                )
                result.add_error(f"{type(e).__name__}: {e}")
            last = result
            # A genuinely-successful OR partially-successful (DEGRADED) engine
            # output counts as a win and stops the chain. Only a hard ERROR
            # keeps falling through to the next engine. (A failed engine still
            # carries placeholder Markdown inside its error result — that must
            # NOT be treated as success; only OK/DEGRADED may stop the chain.)
            if result.status in (ConversionStatus.OK, ConversionStatus.DEGRADED):
                if idx > 0:
                    result.fallback_used = True
                    if result.status == ConversionStatus.OK:
                        result.status = ConversionStatus.DEGRADED
                    result.add_warning(f"fell back to engine '{engine.name}'")
                return result

        if last is None:
            last = DocumentResult(source=source, status=ConversionStatus.ERROR)
            last.add_error("no engine available for this source")
        return last


def get_controller(
    router: EngineRouter | None = None,
    pipeline: ProcessingPipeline | None = None,
) -> ConversionController:
    return ConversionController(router=router, pipeline=pipeline)
