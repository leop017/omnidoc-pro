"""Abstract contracts for OmniDoc Pro's engine / processor layers.

These ABCs are the seam between the *core* and the UI layer: engines and
processors know nothing about Gradio, Tkinter or Click, so the UI can stay a
thin shell. Every concrete engine / cleaner / chunker must subclass one of
these and satisfy the system rules (breadth+depth routing, graceful
degradation, streaming / anti-OOM, dependency minimisation).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from omnidoc.core.document import Chunk, Document, DocumentResult


class EngineInterface(ABC):
    """A document-parsing backend (Deep Engine or MarkItDown Engine).

    ``supports`` performs a cheap, side-effect-free capability check used by
    the router to pick an engine; it must NOT raise. ``available`` reports
    whether the engine's heavy dependencies are importable — the pipeline uses
    this to trigger graceful degradation instead of crashing a batch.
    """

    name: str = "base"

    @abstractmethod
    def supports(self, source: str) -> bool:
        """Return True when this engine can handle ``source`` (a path or URL)."""
        ...

    @abstractmethod
    def convert(self, source: str, config: dict[str, Any]) -> str:
        """Convert ``source`` into a Markdown string.

        ``config`` is the flattened dict form of :class:`OmniDocConfig`
        (see :meth:`OmniDocConfig.to_engine_kwargs`). Implementations may
        raise for unrecoverable errors; the pipeline is responsible for
        catching them and degrading to a fallback engine.
        """
        ...

    def available(self) -> bool:
        """Default: always available. Override when a dep may be missing."""
        return True

    def convert_document(
        self, source: str, config: dict[str, Any]
    ) -> DocumentResult:
        """Rich variant that returns a fully-populated :class:`DocumentResult`.

        The default implementation wraps :meth:`convert`. Engines that can
        emit structured elements / metadata / output paths should override
        this to avoid a second parse pass.
        """
        markdown = self.convert(source, config)
        result = DocumentResult(
            source=source,
            source_format=_source_format(source),
            engine=self.name,
            markdown=markdown,
            document=Document(text=markdown),
        )
        return result


class ProcessorInterface(ABC):
    """A post-processing stage operating on engine output.

    ``process`` returns either a cleaned ``str`` (cleaners / enhancers) or a
    ``List[str]`` (naive splitters). Specialised interfaces below narrow the
    return type so the pipeline can dispatch statically.
    """

    @abstractmethod
    def process(
        self, content: str | Document, config: dict[str, Any]
    ) -> str | list[str]:
        ...


class CleanerInterface(ProcessorInterface):
    """Text / Markdown normaliser (page numbers, duplicate headers, whitespace)."""

    @abstractmethod
    def clean(self, content: str, config: dict[str, Any]) -> str:
        ...

    def process(
        self, content: str | Document, config: dict[str, Any]
    ) -> str:
        text = content.text if isinstance(content, Document) else content
        return self.clean(text, config)


class ChunkerInterface(ABC):
    """Splits a document / text into RAG-ready :class:`Chunk` objects."""

    @abstractmethod
    def chunk(
        self, content: str | Document, config: dict[str, Any]
    ) -> list[Chunk]:
        ...


class EnhancerInterface(ABC):
    """Optional LLM-driven enrichment (image descriptions, metadata).

    Must degrade gracefully: when the LLM is unreachable or ``offline_mode``
    is set, implementations return the input unchanged and record a warning
    on the :class:`DocumentResult` instead of raising.
    """

    @abstractmethod
    def enhance(
        self, result: DocumentResult, config: dict[str, Any]
    ) -> DocumentResult:
        ...


def _source_format(source: str) -> str:
    import os
    import urllib.parse

    if "://" in source:
        return urllib.parse.urlparse(source).path.rsplit("/", 1)[-1] or "url"
    return os.path.splitext(source)[1].lstrip(".").lower()
