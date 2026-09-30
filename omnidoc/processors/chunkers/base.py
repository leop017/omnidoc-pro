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
    # The Deep Engine's multi-sheet Excel path embeds a *nested* list of
    # sheet summaries at metadata["sheets"]. The one-level ``dict(metadata)``
    # above copies only the top-level mapping, so every Chunk would share the
    # same ``list`` object with ``Document.metadata`` and with each other. An
    # in-place mutation downstream (e.g. appending a tag) would then leak
    # across sibling chunks and back into the source Document. Independently
    # copy that one known nested key; the rest of the mapping is already the
    # chunk's own top-level dict, and the inner per-sheet dicts carry only
    # scalars, so a list-level copy is sufficient and side-effect free.
    if "sheets" in meta and isinstance(meta["sheets"], list):
        meta["sheets"] = list(meta["sheets"])
    meta["chunk_index"] = index
    meta["chunk_count"] = total
    return Chunk(text=text, metadata=meta, start_index=start, end_index=end)
