"""Unified, Pydantic-backed configuration for OmniDoc Pro.

One config object drives the whole pipeline: routing (which engine wins),
output format, the cleaning / chunking / enrichment stages, and LLM
settings. UI layers build a config and hand it to the controller — they
never reach into an engine directly.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class LlmSettings(BaseModel):
    """OpenAI- / Ollama-compatible LLM settings (optional enrichment).

    ``enabled`` is the master switch; the pipeline also skips enrichment when
    ``offline_mode`` is set at the top level. ``max_concurrency`` bounds the
    ``asyncio.Semaphore`` used to limit parallel image-description calls.
    """

    enabled: bool = False
    provider: str = "openai"          # "openai" | "ollama"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    prompt: str = ""
    timeout: float = 30.0
    max_concurrency: int = 3

    def is_usable(self) -> bool:
        if not self.enabled or not self.base_url or not self.model:
            return False
        # Ollama's local OpenAI-compatible endpoint accepts any api_key
        # (typically a placeholder like "ollama"); require it only for
        # OpenAI-style providers.
        if self.provider == "ollama":
            return True
        return bool(self.api_key)


class CleaningSettings(BaseModel):
    """Rules for :class:`CleanerInterface` (migrated from WordMdCleaner)."""

    enabled: bool = True
    remove_page_numbers: bool = True
    remove_duplicate_headers: bool = True
    remove_empty_lines: bool = True
    normalize_spaces: bool = True

    def as_rules(self) -> dict[str, bool]:
        return {
            "remove_page_numbers": self.remove_page_numbers,
            "remove_duplicate_headers": self.remove_duplicate_headers,
            "remove_empty_lines": self.remove_empty_lines,
            "normalize_spaces": self.normalize_spaces,
        }


class ChunkingSettings(BaseModel):
    """Settings for the RAG chunkers (fixed / sentence / markdown)."""

    enabled: bool = False
    strategy: Literal["fixed", "sentence", "markdown"] = "fixed"
    chunk_size: int = 512
    chunk_overlap: int = 64
    max_chunk_size: int = 0          # >0 only caps the markdown chunker's split

    def validate_issues(self) -> list[str]:
        """Mirror the chunker-side ValueError rules as human-readable strings.

        Empty list = valid (or chunking disabled). markdown 策略只受
        ``max_chunk_size`` 约束；``chunk_size`` / ``chunk_overlap`` 对它无意义。
        Named ``validate_issues`` (not ``validate``) to avoid clashing with
        Pydantic's own ``BaseModel.validate`` classmethod.
        """
        if not self.enabled:
            return []
        issues: list[str] = []
        if self.strategy in ("fixed", "sentence"):
            if self.chunk_size <= 0:
                issues.append("chunk_size 必须 > 0")
            if self.chunk_overlap < 0 or self.chunk_overlap >= self.chunk_size:
                issues.append("chunk_overlap 必须在 [0, chunk_size) 范围内")
        elif int(self.max_chunk_size) < 0:
            issues.append("chunk_max_size 不能为负数（0=不切分）")
        return issues


class OmniDocConfig(BaseModel):
    """Root configuration for a conversion run."""

    # ── output ────────────────────────────────────────────────
    output_fmt: str = "md"           # "md" | "html" | "json"
    enhanced_md: bool = False        # route markdown through the HTML builder
    output_dir: Optional[str] = None
    preview_chars: int = 5000
    preview_lines: int = 150

    # ── routing / degradation ─────────────────────────────────
    deep_first: bool = True          # prefer Deep Engine for Word/Excel
    allow_fallback: bool = True      # Deep -> MarkItDown fallback on failure

    # ── features ──────────────────────────────────────────────
    offline_mode: bool = False       # skip LLM enrichment, still emit markdown
    llm: LlmSettings = Field(default_factory=LlmSettings)
    cleaning: CleaningSettings = Field(default_factory=CleaningSettings)
    chunking: ChunkingSettings = Field(default_factory=ChunkingSettings)

    # ── escape hatch for UI / CLI specific knobs ──────────────
    extra: dict[str, Any] = Field(default_factory=dict)

    def to_engine_kwargs(self) -> dict[str, Any]:
        """Flatten into the dict form consumed by :meth:`EngineInterface.convert`."""
        return {
            "output_fmt": self.output_fmt,
            "enhanced_md": self.enhanced_md,
            "output_dir": self.output_dir,
            "offline_mode": self.offline_mode,
            "deep_first": self.deep_first,
            "allow_fallback": self.allow_fallback,
            "llm": self.llm.model_dump(),
            "cleaning_rules": self.cleaning.as_rules(),
            "chunking": self.chunking.model_dump(),
            "extra": self.extra,
        }

    @classmethod
    def default(cls) -> OmniDocConfig:
        return cls()
