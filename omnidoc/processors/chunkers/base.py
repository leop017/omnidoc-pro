"""Chunker helpers (ported from ``docconvert.chunkers.base``).

Concrete chunkers subclass :class:`ChunkerInterface` and reuse these two
helpers, which mirror the original :class:`BaseChunker` statics but read
their tuning parameters from the pipeline ``config`` dict.
"""

from __future__ import annotations

from typing import Any

from omnidoc.core.document import Chunk, Document


def coerce_to_document(content: Any) -> Document:
    if isinstance(content, Document):
        return content
    if isinstance(content, str):
        return Document(text=content)
    return Document(text=str(content))


def make_chunk(
    text: str,
    metadata: dict[str, Any],
    *,
    index: int,
    total: int,
    start: int,
    end: int,
) -> Chunk:
    meta = dict(metadata)
    meta["chunk_index"] = index
    meta["chunk_count"] = total
    return Chunk(text=text, metadata=meta, start_index=start, end_index=end)
