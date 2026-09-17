"""RAG chunking strategies (implement :class:`ChunkerInterface`).

The :func:`get_chunker` factory mirrors ``docconvert.chunkers.get_chunker``:
it resolves a strategy name to a chunker instance. Unlike the original,
instances are stateless — all tuning knobs (``chunk_size`` / ``chunk_overlap``
/ ``max_chunk_size``) are read from the pipeline ``config`` dict at
:meth:`ChunkerInterface.chunk` time.
"""

from __future__ import annotations

from typing import Any

from omnidoc.core.interfaces import ChunkerInterface
from omnidoc.processors.chunkers.base import coerce_to_document, make_chunk
from omnidoc.processors.chunkers.fixed_size import FixedSizeChunker
from omnidoc.processors.chunkers.markdown import MarkdownChunker
from omnidoc.processors.chunkers.sentence import SentenceChunker

__all__ = [
    "FixedSizeChunker",
    "MarkdownChunker",
    "SentenceChunker",
    "get_chunker",
    "coerce_to_document",
    "make_chunk",
]


def get_chunker(
    strategy: str, **_: Any
) -> ChunkerInterface:
    """Factory mirroring :func:`docconvert.chunkers.get_chunker`.

    Accepted ``strategy`` values: ``"fixed"`` / ``"fixed_size"``,
    ``"sentence"``, ``"markdown"`` / ``"md"``. Anything else raises
    :class:`ValueError`. (Extra ``**kwargs`` are accepted but ignored — the
    OmniDoc chunkers are stateless and pull their parameters from ``config``.)
    """
    key = strategy.lower()
    if key in {"fixed", "fixed_size"}:
        return FixedSizeChunker()
    if key == "sentence":
        return SentenceChunker()
    if key in {"markdown", "md"}:
        return MarkdownChunker()
    raise ValueError(f"Unsupported chunking strategy: {strategy!r}")
