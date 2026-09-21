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
    """
    elements: list[Element] = []
    last = 0
    for m in _HEADING_RE.finditer(text):
        start = m.start()
        if start > last and text[last:start].strip():
            # Keep the raw slice so `_render` output stays locatable in text.
            elements.append(Element("paragraph", text[last:start].strip()))
        elements.append(Element("heading", m.group(2)))
        last = m.end()
    if last < len(text) and text[last:].strip():
        elements.append(Element("paragraph", text[last:].strip()))
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
        current_body: list[Element] = []

        for elem in doc.elements:
            if elem.element_type == "heading":
                if current_body or current_header:
                    groups.append((current_header, current_body))
                current_header = elem.text
                current_body = []
            else:
                current_body.append(elem)
        if current_body or current_header:
            groups.append((current_header, current_body))

        out: list[Chunk] = []
        total = len(groups)
        cursor = 0
        for i, (header, body) in enumerate(groups):
            text = self._render(header, body)
            start = doc.text.find(text[:40], cursor) if text else cursor
            if start < 0:
                start = cursor
            end = start + len(text)
            cursor = end
            if max_chunk_size and len(text) > max_chunk_size:
                pieces = self._split_long(text, max_chunk_size)
                for j, piece in enumerate(pieces):
                    out.append(
                        make_chunk(
                            text=piece,
                            metadata={**doc.metadata, "header": header, "part": j},
                            index=len(out),
                            total=total * len(pieces),
                            start=start + sum(len(p) for p in pieces[:j]),
                            end=start + sum(len(p) for p in pieces[:j + 1]),
                        )
                    )
            else:
                out.append(
                    make_chunk(
                        text=text,
                        metadata={**doc.metadata, "header": header},
                        index=i,
                        total=total,
                        start=start,
                        end=end,
                    )
                )
        return out

    @staticmethod
    def _render(header: str, body: list[Element]) -> str:
        parts = []
        if header:
            parts.append(f"# {header}")
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
