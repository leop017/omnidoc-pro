"""Header-aware Markdown chunker (ported from ``docconvert.chunkers.markdown``).

Groups consecutive elements under the same heading (and its descendants)
into a single chunk. This is the most useful strategy for OmniDoc output,
because the upstream Markdown files are already split by ``## Section`` /
``### Subsection`` markers.
"""

from __future__ import annotations

import re
from typing import Any

from omnidoc.core.document import Chunk, Document, Element
from omnidoc.core.interfaces import ChunkerInterface
from omnidoc.processors.chunkers.base import coerce_to_document, make_chunk

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$", re.MULTILINE)


def _heading_elements_from_text(text: str) -> list[Element]:
    """Derive a heading/paragraph :class:`Element` sequence from Markdown text.

    Used only when the upstream engine populated ``document.text`` but left
    ``document.elements`` empty (which is the current state of every engine),
    so the header-aware strategy degrades to text parsing instead of silently
    yielding zero chunks.

    Each derived element records its exact byte offset in the source text
    (``start`` / ``end`` in ``metadata``). That lets :meth:`MarkdownChunker.chunk`
    slice the *original* text directly instead of re-rendring it with
    normalized whitespace — so chunk offsets round-trip byte-for-byte even
    when the source uses single newlines, indented code blocks or nested
    lists (anything that does not match the ``"\\n\\n"`` join the renderer
    would produce).
    """
    elements: list[Element] = []
    last = 0
    for m in _HEADING_RE.finditer(text):
        start = m.start()
        if start > last and text[last:start].strip():
            elements.append(
                Element(
                    "paragraph",
                    text[last:start],
                    metadata={"start": last, "end": start},
                )
            )
        # Record the heading level so chunk metadata stays plain, while the
        # exact source offset is what the chunker slices on.
        elements.append(
            Element(
                "heading",
                m.group(2),
                metadata={"level": len(m.group(1)), "start": start, "end": m.end()},
            )
        )
        last = m.end()
    if last < len(text) and text[last:].strip():
        elements.append(
            Element("paragraph", text[last:], metadata={"start": last, "end": len(text)})
        )
    return elements


class MarkdownChunker(ChunkerInterface):
    """Emit one :class:`Chunk` per heading-subtree.

    When the pipeline ``config`` dict carries a positive ``max_chunk_size``,
    any over-long subtree is split into equal slices.
    """

    name = "markdown"

    def chunk(self, content: Any, config: dict[str, Any]) -> list[Chunk]:
        config = config or {}
        max_chunk_size = int(config.get("max_chunk_size", 0)) or None
        doc = coerce_to_document(content)
        if not doc.elements:
            # No engine currently populates ``elements``; degrade to parsing the
            # heading/paragraph structure out of the plain Markdown text so the
            # header-aware strategy still produces chunks instead of silently
            # returning an empty list.
            if not doc.text.strip():
                return []
            doc = Document(text=doc.text, metadata=doc.metadata,
                           elements=_heading_elements_from_text(doc.text))
        if not doc.elements:
            return []

        groups: list[tuple] = []
        current_header = ""
        current_level = 0
        current_body: list[Element] = []

        for elem in doc.elements:
            if elem.element_type == "heading":
                if current_body or current_header:
                    groups.append((current_header, current_level, current_body))
                current_header = elem.text
                current_level = int(elem.metadata.get("level", 0) or 0)
                current_body = [elem]
            else:
                current_body.append(elem)
        if current_body or current_header:
            groups.append((current_header, current_level, current_body))

        # Each group resolves to either an exact source span (elements carry
        # contiguous ``start``/``end`` offsets, set by
        # :func:`_heading_elements_from_text`) or a rendered-text fallback
        # (engine elements without offsets). The source slice is preferred so
        # ``doc.text[start:end] == chunk.text`` round-trips byte-for-byte even
        # when the source uses single newlines / indentation that the
        # ``"\\n\\n"`` join would normalize away.
        pre_split: list[tuple[str, str, int, list[str]]] = []
        cursor = 0
        for header, level, body in groups:
            span = self._group_span(body)
            if span is not None:
                start, end = span
                text = doc.text[start:end]
            else:
                # Engine-provided elements carry no source offsets; render and
                # locate with ``find`` as before.
                body_for_render = body[1:] if body and body[0].element_type == "heading" else body
                text = self._render(header, level, body_for_render)
                start = doc.text.find(text[:40], cursor) if text else cursor
                if start < 0:
                    start = cursor
                end = start + len(text)
                cursor = end
            if max_chunk_size and len(text) > max_chunk_size:
                pieces = self._split_long(text, max_chunk_size)
            else:
                pieces = [text]
            pre_split.append((text, header, start, pieces))
        total = sum(len(p) for _, _, _, p in pre_split)

        out: list[Chunk] = []
        index = 0
        for text, header, start, pieces in pre_split:
            if len(pieces) > 1:
                # O(k) prefix sums instead of re-summing ``pieces[:j]`` for
                # every piece (O(k²) for heavily-split subtrees).
                prefix = [start]
                for piece in pieces:
                    prefix.append(prefix[-1] + len(piece))
                for j, piece in enumerate(pieces):
                    out.append(
                        make_chunk(
                            text=piece,
                            metadata={**doc.metadata, "header": header, "part": j},
                            index=index,
                            total=total,
                            start=prefix[j],
                            end=prefix[j + 1],
                        )
                    )
                    index += 1
            else:
                out.append(
                    make_chunk(
                        text=text,
                        metadata={**doc.metadata, "header": header},
                        index=index,
                        total=total,
                        start=start,
                        end=start + len(text),
                    )
                )
                index += 1
        return out

    @staticmethod
    def _group_span(body: list[Element]) -> tuple[int, int] | None:
        """Return ``(start, end)`` source offsets covering a group, or ``None``.

        A group's elements must carry contiguous, monotonic ``start``/``end``
        metadata (set by :func:`_heading_elements_from_text`) for the span to
        be trustworthy. The group spans from the first element's ``start`` to
        the last element's ``end``; blank runs between them are included so the
        slice stays contiguous in the source.
        """
        spans: list[tuple[int, int]] = []
        for elem in body:
            s, e = elem.metadata.get("start"), elem.metadata.get("end")
            if s is None or e is None:
                return None
            spans.append((s, e))
        spans.sort()
        for i in range(1, len(spans)):
            if spans[i][0] < spans[i - 1][1]:
                # Overlapping / non-monotonic spans — unsafe to slice.
                return None
        return spans[0][0], spans[-1][1]

    @staticmethod
    def _render(header: str, level: int, body: list[Element]) -> str:
        parts = []
        if header:
            # Rebuild the source ``#`` prefix so the rendered text matches the
            # document byte-for-byte (keeps ``find`` offsets accurate). Level
            # is 0 for engine-provided elements without a recorded level, in
            # which case the header is emitted as-is.
            parts.append(f"{'#' * level} {header}" if level else header)
        for elem in body:
            if elem.text:
                parts.append(elem.text)
        return "\n\n".join(parts)

    @staticmethod
    def _split_long(text: str, size: int) -> list[str]:
        if size <= 0:
            return [text]
        out: list[str] = []
        for i in range(0, len(text), size):
            out.append(text[i : i + size])
        return out
