"""Migrated from ``docconvert`` ``tests/test_cleaners.py``.

The OmniDoc :class:`WordMdCleaner` follows :class:`CleanerInterface`: the
four rule flags are read from the pipeline ``config`` dict (``config["cleaning_rules"]``)
instead of an ``AppConfig``. The original tests built
``WordMdCleaner(AppConfig(cleaning_rules=...))``; the ported equivalent is
``WordMdCleaner(rules)`` (fixed-rules constructor), while the config-driven
variant passes ``{"cleaning_rules": rules}`` per call. All page-number /
code-block / whitespace assertions are kept verbatim.
"""

import unittest

from omnidoc.processors.cleaners.word_md import WordMdCleaner

_ALL = {
    "remove_page_numbers": True,
    "remove_duplicate_headers": True,
    "remove_empty_lines": True,
    "normalize_spaces": True,
}
_NONE = {k: False for k in _ALL}


class TestWordMdCleaner(unittest.TestCase):

    def setUp(self):
        self.cleaner = WordMdCleaner(dict(_ALL))

    def clean(self, text):
        return self.cleaner.clean(text, {})

    def test_empty_input_returns_empty(self):
        self.assertEqual(self.clean(""), "")

    def test_preserves_normal_lines(self):
        text = "# Title\nSome content\nMore content"
        self.assertEqual(self.clean(text), text)

    def test_removes_bracket_page_numbers(self):
        self.assertNotIn("[1]", self.clean("para1\n[1]\npara2"))
        self.assertNotIn("[42]", self.clean("para1\n[42]\npara2"))

    def test_removes_chinese_page_markers(self):
        self.assertNotIn("第1页", self.clean("para1\n第1页\npara2"))
        self.assertNotIn("第 5 页", self.clean("para1\n第 5 页\npara2"))

    def test_removes_dash_page_numbers(self):
        self.assertNotIn("- 1 -", self.clean("para1\n- 1 -\npara2"))
        self.assertNotIn("-12-", self.clean("para1\n-12-\npara2"))

    def test_removes_english_page_markers(self):
        for marker in ("Page 1", "page 5", "PAGE 10", "Pág. 3", "P. 7"):
            cleaned = self.clean(f"para1\n{marker}\npara2")
            self.assertNotIn(marker, cleaned, f"Failed to remove: {marker}")

    def test_preserves_empty_lines_as_separators(self):
        text = "para1\n\npara2"
        self.assertEqual(self.clean(text), text)

    def test_does_not_remove_numbered_list_items(self):
        text = "1. First item\n2. Second item"
        self.assertEqual(self.clean(text), text)

    def test_does_not_remove_inline_numbers(self):
        text = "Item 42 in stock"
        self.assertEqual(self.clean(text), text)

    def test_removes_page_of_form(self):
        for marker in ("Page 1 of 10", "page 3 of 5", "PAGE 10 OF 20"):
            cleaned = self.clean(f"para1\n{marker}\npara2")
            self.assertNotIn(marker, cleaned, f"Failed to remove: {marker}")

    def test_removes_page_slash_form(self):
        for marker in ("Page 1 / 10", "page 3 / 5"):
            cleaned = self.clean(f"para1\n{marker}\npara2")
            self.assertNotIn(marker, cleaned, f"Failed to remove: {marker}")

    def test_preserves_fraction_not_paired_with_page(self):
        # "5 of 10" alone is too ambiguous (ratios, scores) to drop
        self.assertEqual(
            self.clean("para1\n5 of 10\npara2"),
            "para1\n5 of 10\npara2",
        )

    def test_preserves_page_word_in_body(self):
        # "Page" as a noun in body text must not trigger the rule
        self.assertEqual(
            self.clean("See Page 5 for details"),
            "See Page 5 for details",
        )

    def test_does_not_remove_page_sentence(self):
        # Page markers must be anchored; "Page 5 explains ..." is body text,
        # not a page number, even though it starts with a page-marker prefix.
        line = "Page 5 explains the methodology in detail"
        self.assertEqual(self.clean(line), line)
        line2 = "P. 7 is an important milestone"
        self.assertEqual(self.clean(line2), line2)

    def test_preserves_unrelated_abbreviations(self):
        # P. as initial (e.g. "P. Smith") should not match
        self.assertEqual(
            self.clean("P. Smith wrote this"),
            "P. Smith wrote this",
        )

    def test_handles_mammoth_backslash_escapes(self):
        # Bug fix: mammoth escapes markdown punctuation in its output
        # (``[1]`` -> ``\\[1\\]``, ``- 1 -`` -> ``\\- 1 \\-``, ``P. 7`` ->
        # ``P\\. 7``). The cleaner must normalize these before matching
        # so the existing rules still trigger.
        for raw, expected_remaining in (
            ("\\[1\\]", ""),
            ("\\- 1 \\-", ""),
            ("\\-12\\-", ""),
            ("P\\. 7", ""),
            ("Pág\\. 3", ""),
            ("\\[12\\]", ""),
        ):
            with self.subTest(raw=raw):
                self.assertNotIn(expected_remaining or raw, self.clean(raw))

    def test_escape_preserves_body_text(self):
        # The unescape step must not break body content that genuinely
        # uses backslashes or markdown punctuation.
        self.assertEqual(
            self.clean("See P\\. Smith on page 5"),
            "See P\\. Smith on page 5",
        )


def _cleaner_with(**rules):
    merged = dict(_NONE)
    merged.update(rules)
    return WordMdCleaner(merged)


class TestWordMdCleanerEmptyLineCollapse(unittest.TestCase):
    """``remove_empty_lines`` — collapse runs of ≥2 empty lines into one."""

    def test_collapses_three_empty_lines_to_one(self):
        c = _cleaner_with(remove_empty_lines=True)
        self.assertEqual(c.clean("a\n\n\n\nb", {}), "a\n\nb")

    def test_preserves_single_empty_line_as_paragraph_separator(self):
        c = _cleaner_with(remove_empty_lines=True)
        self.assertEqual(c.clean("a\n\nb", {}), "a\n\nb")

    def test_whitespace_only_lines_count_as_empty(self):
        c = _cleaner_with(remove_empty_lines=True)
        # "   " and "\t" are whitespace-only — should be collapsed
        self.assertEqual(c.clean("a\n   \n\t\n   \nb", {}), "a\n\nb")

    def test_no_op_when_disabled(self):
        c = WordMdCleaner(dict(_NONE))
        self.assertEqual(c.clean("a\n\n\n\nb", {}), "a\n\n\n\nb")


class TestWordMdCleanerNormalizeSpaces(unittest.TestCase):
    """``normalize_spaces`` — full-width space, tabs, internal runs, trailing."""

    def test_collapses_internal_runs_of_spaces(self):
        c = _cleaner_with(normalize_spaces=True)
        self.assertEqual(c.clean("hello   world", {}), "hello world")

    def test_converts_tabs_to_single_space(self):
        c = _cleaner_with(normalize_spaces=True)
        self.assertEqual(c.clean("hello\tworld", {}), "hello world")

    def test_converts_fullwidth_space_to_regular(self):
        # U+3000 IDEOGRAPHIC SPACE used in CJK typography
        c = _cleaner_with(normalize_spaces=True)
        self.assertEqual(c.clean("hello\u3000world", {}), "hello world")

    def test_strips_trailing_whitespace(self):
        c = _cleaner_with(normalize_spaces=True)
        self.assertEqual(c.clean("hello   ", {}), "hello")
        self.assertEqual(c.clean("hello\t\t  ", {}), "hello")

    def test_preserves_leading_whitespace(self):
        # Indentation matters in markdown (code blocks, lists, tables)
        c = _cleaner_with(normalize_spaces=True)
        self.assertEqual(c.clean("    indented line", {}), "    indented line")
        # Leading tab is preserved verbatim — converting it to 1 space
        # could break tab-indented list items or code blocks
        self.assertEqual(c.clean("\tindented line", {}), "\tindented line")

    def test_leaves_all_whitespace_line_for_empty_pass(self):
        c = _cleaner_with(normalize_spaces=True)
        # An all-whitespace line is left untouched here; the
        # remove_empty_lines pass is responsible for collapsing.
        self.assertEqual(c.clean("   ", {}), "   ")

    def test_preserves_indented_code_block_spacing(self):
        # Internal spacing inside an indented code block is significant;
        # collapsing it would corrupt the code.
        c = _cleaner_with(normalize_spaces=True)
        self.assertEqual(
            c.clean("    x = a    b\n    y = 1", {}),
            "    x = a    b\n    y = 1",
        )

    def test_preserves_fenced_code_block_spacing(self):
        c = _cleaner_with(normalize_spaces=True)
        text = "```python\nz = a    b\n```"
        self.assertEqual(c.clean(text, {}), text)

    def test_body_text_still_normalized(self):
        c = _cleaner_with(normalize_spaces=True)
        # Non-code lines keep collapsing internal runs.
        self.assertEqual(c.clean("hello   world", {}), "hello world")
        self.assertEqual(c.clean("  hello   world", {}), "  hello world")

    def test_no_op_when_disabled(self):
        c = WordMdCleaner(dict(_NONE))
        self.assertEqual(c.clean("hello   world  ", {}), "hello   world  ")


class TestWordMdCleanerDedupeConsecutive(unittest.TestCase):
    """``remove_duplicate_headers`` — drop consecutive duplicate non-empty lines."""

    def test_drops_consecutive_duplicates(self):
        c = _cleaner_with(remove_duplicate_headers=True)
        self.assertEqual(
            c.clean("Header\nHeader\nHeader\nbody", {}),
            "Header\nbody",
        )

    def test_keeps_non_adjacent_duplicates(self):
        c = _cleaner_with(remove_duplicate_headers=True)
        self.assertEqual(c.clean("a\nb\na\nb\na", {}), "a\nb\na\nb\na")

    def test_two_identical_lines_become_one(self):
        c = _cleaner_with(remove_duplicate_headers=True)
        self.assertEqual(c.clean("a\na", {}), "a")

    def test_normalize_runs_first_so_whitespace_diffs_dedup(self):
        # When paired with normalize_spaces, lines that differ only in
        # whitespace should also be deduped (normalize runs first).
        c = _cleaner_with(remove_duplicate_headers=True, normalize_spaces=True)
        self.assertEqual(c.clean("a\nb   \nb\t\nc", {}), "a\nb\nc")

    def test_empty_lines_not_deduped_by_this_rule(self):
        # Empty lines are deduped by remove_empty_lines, not here
        c = _cleaner_with(remove_duplicate_headers=True)
        self.assertEqual(c.clean("a\n\n\nb", {}), "a\n\n\nb")

    def test_no_op_when_disabled(self):
        c = WordMdCleaner(dict(_NONE))
        self.assertEqual(c.clean("a\na\na", {}), "a\na\na")


class TestWordMdCleanerAllRulesCombined(unittest.TestCase):
    """All four rules work together without interfering."""

    def test_all_four_active_full_pipeline(self):
        c = WordMdCleaner(dict(_ALL))
        text = (
            "[1]\n"
            "第3页\n"
            "para 1\n"
            "para 1\n"
            "para 2\n"
            "\n"
            "\n"
            "\n"
            "para 3\n"
        )
        # Page numbers removed, consecutive "para 1" deduped, blank
        # lines collapsed, internal spaces normalized. The trailing
        # newline from the input is preserved (split -> join round-trip).
        self.assertEqual(c.clean(text, {}), "para 1\npara 2\n\npara 3\n")


class TestWordMdCleanerCodeBlockProtection(unittest.TestCase):
    """All four rules must leave code blocks (fenced and indented) untouched."""

    def _cleaner(self, **overrides):
        rules = dict(_ALL)
        rules.update(overrides)
        return WordMdCleaner(rules)

    def test_fenced_page_markers_not_removed(self):
        c = self._cleaner()
        text = "```\n[1]\n- 1 -\nPage 1\n```"
        self.assertEqual(c.clean(text, {}), text)

    def test_fenced_blank_lines_not_collapsed(self):
        c = self._cleaner()
        text = "```\na\n\n\nb\n```"
        self.assertEqual(c.clean(text, {}), text)

    def test_fenced_duplicate_lines_not_deduped(self):
        c = self._cleaner()
        text = "```\nx = 1\nx = 1\n```"
        self.assertEqual(c.clean(text, {}), text)

    def test_fenced_internal_spacing_preserved(self):
        c = self._cleaner()
        text = "```\nreturn a    b\n```"
        self.assertEqual(c.clean(text, {}), text)

    def test_indented_page_markers_not_removed(self):
        c = self._cleaner()
        text = "    [1]\n    Page 1"
        self.assertEqual(c.clean(text, {}), text)

    def test_indented_duplicate_lines_not_deduped(self):
        c = self._cleaner()
        text = "    x = 1\n    x = 1"
        self.assertEqual(c.clean(text, {}), text)

    def test_indented_blank_lines_not_collapsed(self):
        # Only the indented lines are code; blank runs between them are
        # ordinary paragraph separators and still collapse to one.
        c = self._cleaner()
        self.assertEqual(c.clean("    a\n\n\n    b", {}), "    a\n\n    b")

    def test_code_protected_while_body_still_cleaned(self):
        c = self._cleaner()
        text = (
            "[1]\n"
            "```\n"
            "[2]\n"
            "a    b\n"
            "\n"
            "\n"
            "x = 1\n"
            "x = 1\n"
            "```\n"
            "para\n"
            "para\n"
        )
        # Outside the fence: [1] removed, "para" deduped. Inside the
        # fence: page marker, internal spacing, blank run and duplicate
        # lines all preserved verbatim.
        self.assertEqual(
            c.clean(text, {}),
            "```\n[2]\na    b\n\n\nx = 1\nx = 1\n```\npara\n",
        )


class TestWordMdCleanerConfigDriven(unittest.TestCase):
    """The pipeline ``config`` dict (``config["cleaning_rules"]``) gates rule
    activation when the cleaner is constructed without fixed rules — the
    replacement for the original ``AppConfig`` gating tests."""

    def _text_with_page_markers(self):
        return "para1\n[1]\n第2页\n- 3 -\nPage 4 of 5\npara5"

    def test_pipeline_config_keeps_all_rules_active(self):
        cleaner = WordMdCleaner()
        out = cleaner.clean(self._text_with_page_markers(), {"cleaning_rules": dict(_ALL)})
        self.assertEqual(out, "para1\npara5")

    def test_disabling_page_numbers_preserves_them(self):
        cleaner = WordMdCleaner()
        out = cleaner.clean(self._text_with_page_markers(), {"cleaning_rules": dict(_NONE)})
        self.assertIn("[1]", out)
        self.assertIn("第2页", out)
        self.assertIn("- 3 -", out)
        self.assertIn("Page 4 of 5", out)
        self.assertIn("para1", out)
        self.assertIn("para5", out)

    def test_absent_rules_pass_through(self):
        cleaner = WordMdCleaner()
        self.assertEqual(cleaner.clean("", {}), "")
        self.assertEqual(
            cleaner.clean(self._text_with_page_markers(), {}),
            self._text_with_page_markers(),
        )

    def test_independent_rule_flags(self):
        # The 3 non-page-number rules are independent: enabling one
        # does not turn on any other. Page-number removal still works
        # regardless of the other flags.
        cleaner = WordMdCleaner()
        out = cleaner.clean("para1\n[1]\npara2", {"cleaning_rules": dict(_NONE, **{"remove_page_numbers": True})})
        self.assertNotIn("[1]", out)

    def test_fixed_constructor_rules_win_over_config(self):
        cleaner = WordMdCleaner(dict(_NONE))
        # Fixed (disabled) rules take precedence over a config that enables them.
        out = cleaner.clean("para1\n[1]\npara2", {"cleaning_rules": dict(_ALL)})
        self.assertIn("[1]", out)


if __name__ == "__main__":
    unittest.main()
