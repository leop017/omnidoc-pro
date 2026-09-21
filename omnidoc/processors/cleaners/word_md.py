"""Word -> Markdown cleaner (ported from ``docconvert.cleaners.word_md``).

A faithful migration of the original :class:`WordMdCleaner` algorithm: five
page-number regex rules, fenced/indented code-block masking, and the four
document-level passes (line rules -> collapse empty -> normalize spaces ->
dedupe consecutive). The only change is the signature, which now conforms to
:class:`CleanerInterface` and reads its rule flags from the flattened engine
kwargs dict (``config["cleaning_rules"]``) instead of an ``AppConfig``.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from omnidoc.core.interfaces import CleanerInterface

_UNESCAPE_PATTERN = re.compile(r"\\([\\\[\]\-.\(\)])")
_HORIZ_WS_PATTERN = re.compile(r"[ \t]+")
_FULLWIDTH_SPACE = "\u3000"
# A line that opens or closes a fenced code block (``` or ~~~), possibly
# with a language tag: "```python". Used to keep code-block whitespace intact.
_FENCE_PATTERN = re.compile(r"^\s*(?:`{3,}|~{3,})")


class WordMdCleaner(CleanerInterface):
    """Defense-in-depth post-processor for Word -> Markdown output.

    Page-number rules (line-level, anchored to ``strip()`` so they only
    match standalone markers, never page numbers embedded in body text):

    - Inline refs: [1], [12]
    - Chinese: 第3页, 第 5 页
    - Bordered: - 1 -, -12-
    - Western: Page 1, page 5, Pág. 3, P. 7
    - Multi-form: Page 1 of 10, Page 3 / 10

    Document-level rules: ``remove_duplicate_headers`` (drop consecutive
    duplicate lines), ``remove_empty_lines`` (collapse >=2 empty lines to
    one), ``normalize_spaces`` (U+3000 + tabs -> single space, collapse
    internal horizontal whitespace, strip trailing). All four skip lines
    inside fenced (```` ``` ```` / ``~~~``) or indented (>=4 leading
    spaces) code blocks.
    """

    _RULES = (
        re.compile(r"^\[\d+\]$"),
        re.compile(r"^第\s*\d+\s*页$"),
        re.compile(r"^-\s*\d+\s*-$"),
        re.compile(r"^page\s*\d+\s*(?:of|/)\s*\d+\s*$", re.IGNORECASE),
        re.compile(r"^(?:Page|Pág\.|P\.)\s*\d+\s*$", re.IGNORECASE),
    )

    _LINE_RULE_GROUPS: dict[str, tuple] = {
        "remove_page_numbers": (0, 1, 2, 3, 4),
    }

    def __init__(self, cleaning_rules: Optional[dict[str, bool]] = None):
        # Optional override used when the cleaner is driven directly rather
        # than through the pipeline. When provided, ``clean`` ignores the
        # per-call ``config`` rules and uses these.
        self._fixed_rules = cleaning_rules

    # ── CleanerInterface ───────────────────────────────────────

    def clean(self, content: str, config: dict[str, Any]) -> str:
        rules = self._fixed_rules or config.get("cleaning_rules", {})
        active = self._resolve_line_rules(rules)
        collapse_empty = bool(rules.get("remove_empty_lines", False))
        normalize = bool(rules.get("normalize_spaces", False))
        dedupe = bool(rules.get("remove_duplicate_headers", False))

        if not any((active, collapse_empty, normalize, dedupe)):
            return content

        lines = content.split("\n")
        # Classify code-block lines ONCE so every rule below can leave code
        # untouched: page markers, blank lines, repeated lines and internal
        # spacing are all significant inside code.
        code_mask = self._code_mask(lines)

        # Stage 1: line-level rules (page numbers).
        if active:
            lines, code_mask = self._apply_line_rules(lines, code_mask, active)

        # Stage 2: collapse empty lines.
        if collapse_empty:
            lines, code_mask = self._collapse_empty_lines(lines, code_mask)

        # Stage 3: normalize spaces within each line.
        if normalize:
            lines = self._normalize_lines_spaces(lines, code_mask)

        # Stage 4: drop consecutive duplicate lines.
        if dedupe:
            lines = self._dedupe_consecutive_lines(lines, code_mask)

        return "\n".join(lines)

    # ── internals (algorithm-identical to the original) ───────

    def _resolve_line_rules(self, cleaning_rules: dict[str, bool]) -> tuple:
        active: list[int] = []
        for key, indices in self._LINE_RULE_GROUPS.items():
            if cleaning_rules.get(key, False):
                active.extend(indices)
        return tuple(self._RULES[i] for i in active)

    def _code_mask(self, lines: list[str]) -> list[bool]:
        in_fence = False
        mask: list[bool] = []
        for line in lines:
            if _FENCE_PATTERN.match(line):
                in_fence = not in_fence
                mask.append(True)
                continue
            mask.append(in_fence or self._is_code_line(line))
        return mask

    def _apply_line_rules(
        self, lines: list[str], code_mask: list[bool], active: tuple
    ):
        kept: list[str] = []
        kept_mask: list[bool] = []
        for line, code in zip(lines, code_mask):
            stripped = line.strip()
            if not stripped:
                kept.append(line)
                kept_mask.append(code)
                continue
            if code:
                kept.append(line)
                kept_mask.append(True)
                continue
            normalized = _UNESCAPE_PATTERN.sub(r"\1", stripped)
            if any(rx.match(normalized) for rx in active):
                continue
            kept.append(line)
            kept_mask.append(code)
        return kept, kept_mask

    @staticmethod
    def _collapse_empty_lines(lines: list[str], code_mask: list[bool]):
        result: list[str] = []
        result_mask: list[bool] = []
        prev_empty = False
        prev_code = False
        for line, code in zip(lines, code_mask):
            is_empty = not line.strip()
            if is_empty and prev_empty and not (code and prev_code):
                continue
            result.append("" if is_empty else line)
            result_mask.append(code)
            prev_empty = is_empty
            prev_code = code
        return result, result_mask

    def _normalize_lines_spaces(self, lines: list[str], code_mask: list[bool]) -> list[str]:
        result: list[str] = []
        for line, code in zip(lines, code_mask):
            result.append(self._normalize_line_spaces(line, code_line=code))
        return result

    @staticmethod
    def _is_code_line(line: str) -> bool:
        return len(line) - len(line.lstrip(" \t")) >= 4

    @staticmethod
    def _normalize_line_spaces(line: str, code_line: bool = False) -> str:
        line = line.replace(_FULLWIDTH_SPACE, " ")
        if not line.strip():
            return line
        if code_line:
            return line.rstrip()
        match = re.match(r"^([ \t]*)(.*?)([ \t]*)$", line, re.DOTALL)
        if not match:
            return line.rstrip()
        leading, middle, _trailing = match.groups()
        middle = _HORIZ_WS_PATTERN.sub(" ", middle)
        return leading + middle

    @staticmethod
    def _dedupe_consecutive_lines(lines: list[str], code_mask: list[bool]) -> list[str]:
        result: list[str] = []
        prev: Optional[str] = None
        prev_code = False
        for line, code in zip(lines, code_mask):
            if line.strip() and line == prev and not (code and prev_code):
                continue
            result.append(line)
            prev = line
            prev_code = code
        return result
