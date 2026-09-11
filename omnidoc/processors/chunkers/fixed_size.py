"""Fixed-size character window chunker (ported from ``docconvert.chunkers.fixed_size``).

Splits the document into overlapping windows of ``chunk_size`` characters
with ``chunk_overlap`` characters of shared context between neighbours.
This is the lowest-common-denominator strategy: it works on any text but
has no semantic awareness, so a chunk can cut a sentence in half.
"""

from __future__ import annotations

from typing import Any

from omnidoc.core.document import Chunk
from omnidoc.core.interfaces import ChunkerInterface
from omnidoc.processors.chunkers.base import coerce_to_document, make_chunk

DEFAULT_CHUNK_SIZE = 512
DEFAULT_OVERLAP = 64


class FixedSizeChunker(ChunkerInterface):
    """Sliding-window chunker measured in characters.

    Reads ``chunk_size`` / ``chunk_overlap`` from the pipeline ``config``
    dict (falling back to the defaults below when absent).
    """

    name = "fixed"

    def chunk(self, content: Any, config: dict[str, Any]) -> list[Chunk]:
        config = config or {}
        size = int(config.get("chunk_size", DEFAULT_CHUNK_SIZE))
        overlap = int(config.get("chunk_overlap", DEFAULT_OVERLAP))
        if size <= 0:
            raise ValueError("chunk_size must be > 0")
        if overlap < 0 or overlap >= size:
            raise ValueError("chunk_overlap must be in [0, chunk_size)")

        doc = coerce_to_document(content)
        text = doc.text
        if not text:
            return []

        step = size - overlap
        spans: list[tuple] = []
        start = 0
        n = len(text)
        while start < n:
            end = min(start + size, n)
            spans.append((start, end))
            if end == n:
                break
            start += step

        total = len(spans)
        return [
            make_chunk(
                text=text[s:e],
                metadata=doc.metadata,
                index=i,
                total=total,
                start=s,
                end=e,
            )
            for i, (s, e) in enumerate(spans)
        ]
