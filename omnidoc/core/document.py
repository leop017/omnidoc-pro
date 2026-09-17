"""Unified document data model for OmniDoc Pro.

The :class:`Document` / :class:`Chunk` / :class:`Element` primitives are the
common currency between parsers, engines, chunkers and the LLM enrichment
layer (migrated from ``docconvert.parsers.models``). :class:`DocumentResult`
is the top-level return value of the pipeline: it carries both the raw
Markdown produced by an engine and the RAG-ready chunks / metadata, plus the
diagnostics needed to surface graceful-degradation warnings to callers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class ConversionStatus(str, Enum):
    """Outcome of a single source through the pipeline."""

    OK = "ok"
    DEGRADED = "degraded"          # engine fell back (e.g. deep -> markitdown)
    ERROR = "error"                # no engine could produce a result


@dataclass
class Element:
    """A single block-level unit recovered from the source document.

    ``element_type`` is one of: ``heading``, ``paragraph``, ``list``,
    ``code``, ``table``, ``image``, ``other``. The string is intentionally
    loose (no enum) so third-party parsers can introduce new types without
    breaking the public contract.
    """

    element_type: str = "other"
    text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Document:
    """A parsed document — the shared currency between parsers and chunkers.

    ``text`` is the flattened plain/Markdown view (always safe to use as a
    fallback). ``elements`` preserves structural information when the parser
    recovered it. ``metadata`` carries format-specific hints.
    """

    text: str = ""
    elements: list[Element] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Chunk:
    """A contiguous slice of a :class:`Document`, ready for embedding.

    ``text`` is what downstream consumers feed to an embedding model;
    ``metadata`` is copied (shallow) from the parent and augmented with
    chunk-local hints such as ``chunk_index`` and ``chunk_count``.
    """

    text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    start_index: int = 0
    end_index: int = 0


@dataclass
class DocumentResult:
    """Top-level result of running one source through the pipeline.

    Callers (controllers, UI, CLI) consume this single object. It is
    deliberately self-describing: ``status`` tells you whether the result is
    trustworthy, ``engine`` + ``fallback_used`` explain which path was taken,
    and ``warnings`` / ``errors`` carry non-fatal diagnostics so that a
    single degraded file never aborts a whole batch.
    """

    source: str
    source_format: str = ""
    engine: str = ""
    status: ConversionStatus = ConversionStatus.OK
    fallback_used: bool = False

    markdown: str = ""
    document: Document = field(default_factory=Document)
    chunks: list[Chunk] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    output_paths: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    elapsed: float = 0.0

    @property
    def success(self) -> bool:
        return self.status in (ConversionStatus.OK, ConversionStatus.DEGRADED) and bool(
            self.markdown or self.chunks
        )

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)

    def add_error(self, message: str) -> Optional[None]:
        self.errors.append(message)
        return None

    def to_dict(self, include_markdown: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "source": self.source,
            "source_format": self.source_format,
            "engine": self.engine,
            "status": self.status.value,
            "fallback_used": self.fallback_used,
            "success": self.success,
            "chunk_count": len(self.chunks),
            "metadata": self.metadata,
            "output_paths": self.output_paths,
            "warnings": self.warnings,
            "errors": self.errors,
            "elapsed": self.elapsed,
        }
        if include_markdown:
            payload["markdown"] = self.markdown
        payload["chunks"] = [
            {
                "text": c.text,
                "metadata": c.metadata,
                "start_index": c.start_index,
                "end_index": c.end_index,
            }
            for c in self.chunks
        ]
        return payload
