"""Sentence-boundary chunker (ported from ``docconvert.chunkers.sentence``).

Greedily accumulates sentences until the running window reaches
``chunk_size`` characters, then emits a chunk and starts a new window that
reuses up to ``chunk_overlap`` characters of context. Boundary detection
is heuristic: any of ``.``, ``!``, ``?``, ``。``, ``!``, ``?`` followed by
whitespace or end-of-string.
"""

from __future__ import annotations

import re
from typing import Any, NamedTuple

from omnidoc.core.document import Chunk
from omnidoc.core.interfaces import ChunkerInterface
from omnidoc.processors.chunkers.base import coerce_to_document, make_chunk

_BOUNDARY_RE = re.compile(r"(?<=[.!?。!?])\s+")

DEFAULT_CHUNK_SIZE = 512
DEFAULT_OVERLAP = 64


class _Sentence(NamedTuple):
    """A sentence with its exact start offset in the source text."""

    text: str
    start: int


def _split_with_offsets(text: str) -> list[_Sentence]:
    """Split ``text`` on sentence boundaries while recording each
    sentence's true start offset (required for accurate ``start_index`` /
    ``end_index`` metadata in :class:`Chunk`).
    """
    out: list[_Sentence] = []
    pos = 0
    for m in _BOUNDARY_RE.finditer(text):
        seg = text[pos:m.start()]
        seg_stripped = seg.rstrip()
        if seg_stripped:
            out.append(_Sentence(seg_stripped, pos + (len(seg) - len(seg_stripped))))
        pos = m.end()
    tail = text[pos:].rstrip()
    if tail:
        out.append(_Sentence(tail, pos + (len(text) - pos - len(tail))))
    return out


class SentenceChunker(ChunkerInterface):
    """Chunk on sentence boundaries while staying under ``chunk_size``.

    Reads ``chunk_size`` / ``chunk_overlap`` from the pipeline ``config``
    dict (falling back to the defaults below when absent).

    ``start_index`` / ``end_index`` on each emitted :class:`Chunk` are
    **byte offsets into the original (stripped) source text**: the
    sentence-boundary walk records the exact position of every sentence,
    so offsets are not re-inferred via ``str.find`` heuristics.
    """

    name = "sentence"

    def chunk(self, content: Any, config: dict[str, Any]) -> list[Chunk]:
        config = config or {}
        size = int(config.get("chunk_size", DEFAULT_CHUNK_SIZE))
        overlap = int(config.get("chunk_overlap", DEFAULT_OVERLAP))
        if size <= 0:
            raise ValueError("chunk_size must be > 0")
        if overlap < 0 or overlap >= size:
            raise ValueError("chunk_overlap must be in [0, chunk_size)")

        doc = coerce_to_document(content)
        text = doc.text.strip()
        if not text:
            return []

        sentences = _split_with_offsets(text)
        if not sentences:
            return []

        # Walk the sentences greedily; for each emitted chunk we keep the
        # true source-text start offset of its first sentence and the end
        # offset of its last sentence.
        spans: list[tuple[int, int]] = []  # (start_off, end_off) per chunk
        pending: list[tuple[int, int]] = []  # (start_off, end_off) per sentence
        pending_len = 0

        def _flush() -> None:
            nonlocal pending, pending_len
            if pending:
                spans.append((pending[0][0], pending[-1][1]))
                pending, pending_len = [], 0

        for s, s_start in sentences:
            s_end = s_start + len(s)
            add_len = len(s) + (1 if pending else 0)
            if pending and pending_len + add_len > size:
                _flush()
                if overlap > 0 and spans:
                    # Re-anchor: the new window starts at the last
                    # ``overlap`` characters of the previous span so the
                    # next chunk can reuse that context without breaking
                    # its source offsets.
                    prev_end = spans[-1][1]
                    anchor = max(spans[-1][0], prev_end - overlap)
                    pending = [(anchor, prev_end)]
                    pending_len = prev_end - anchor
            pending.append((s_start, s_end))
            pending_len += add_len
        _flush()

        total = len(spans)
        out: list[Chunk] = []
        for i, (start, end) in enumerate(spans):
            out.append(
                make_chunk(
                    text=text[start:end],
                    metadata=doc.metadata,
                    index=i,
                    total=total,
                    start=start,
                    end=end,
                )
            )
        return out
