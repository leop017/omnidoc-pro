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
        router: EngineRouter = None,
        pipeline: ProcessingPipeline = None,
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
        t0 = time.perf_counter()
        result = self._convert_with_fallback(source, cfg)
        self.pipeline.run(result, cfg)
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
        return [self._convert_one(s, cfg) for s in sources]

    def _convert_one(
        self, source: str, cfg: dict[str, Any]
    ) -> DocumentResult:
        t0 = time.perf_counter()
        result = self._convert_with_fallback(source, cfg)
        self.pipeline.run(result, cfg)
        result.elapsed = time.perf_counter() - t0
        return result

    # ── engine selection with graceful degradation ─────────────

    def _convert_with_fallback(
        self, source: str, cfg: dict[str, Any]
    ) -> DocumentResult:
        chain: list[EngineInterface] = self.router.fallback_chain(source, cfg)
        if not cfg.get("allow_fallback", True):
            chain = chain[:1]

        last: DocumentResult = None
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
            if result.markdown:
                if idx > 0:
                    result.fallback_used = True
                    result.status = ConversionStatus.DEGRADED
                    result.add_warning(f"fell back to engine '{engine.name}'")
                return result

        if last is None:
            last = DocumentResult(source=source, status=ConversionStatus.ERROR)
            last.add_error("no engine available for this source")
        return last


def get_controller(
    router: EngineRouter = None,
    pipeline: ProcessingPipeline = None,
) -> ConversionController:
    return ConversionController(router=router, pipeline=pipeline)
