"""Migrated from ``docconvert`` ``tests/test_utils.py`` -> ``omnidoc.engines.deep._utils``.

The helpers were ported algorithm-identically into the Deep Engine, so the
assertions are kept verbatim; only the import paths change.
"""

import unittest

from omnidoc.engines.deep._utils import (
    INVALID_NAMES,
    clean_filename,
    decode_text,
    escape_md_cell,
    html_to_md,
    safe_str,
)


class TestSafeStr(unittest.TestCase):

    def test_none_returns_empty_string(self):
        self.assertEqual(safe_str(None), "")

    def test_nan_float_returns_empty_string(self):
        self.assertEqual(safe_str(float("nan")), "")

    def test_pandas_na_returns_empty_string(self):
        try:
            import pandas as pd
        except ImportError:
            self.skipTest("pandas not available")
        self.assertEqual(safe_str(pd.NA), "")
        self.assertEqual(safe_str(pd.NaT), "")

    def test_zero_value_is_preserved(self):
        self.assertEqual(safe_str(0), "0")
        self.assertEqual(safe_str(0.0), "0.0")

    def test_false_value_is_preserved(self):
        self.assertEqual(safe_str(False), "False")

    def test_empty_string_is_preserved(self):
        self.assertEqual(safe_str(""), "")

    def test_crlf_normalized_to_single_lf(self):
        # CRLF normalizes to a single LF (not LF+LF, which would insert a
        # spurious blank line into Excel cell content).
        self.assertEqual(safe_str("a\rb"), "a\nb")
        self.assertEqual(safe_str("a\r\nb"), "a\nb")
        # Bare CR in the middle of a line is also normalized
        self.assertEqual(safe_str("a\rb\rc"), "a\nb\nc")

    def test_plain_string_unchanged(self):
        self.assertEqual(safe_str("hello"), "hello")

    def test_int_value_stringified(self):
        self.assertEqual(safe_str(42), "42")

    def test_list_value_stringified(self):
        # List input must fall back to str() — pd.isna() raises on lists.
        result = safe_str([1, 2, 3])
        self.assertIn("1", result)
        self.assertIn("2", result)
        self.assertIn("3", result)

    def test_dict_value_stringified(self):
        result = safe_str({"a": 1, "b": 2})
        self.assertIn("a", result)
        self.assertIn("1", result)
        self.assertIn("b", result)
        self.assertIn("2", result)

    def test_tuple_value_stringified(self):
        self.assertIn("1", safe_str((1, 2)))

    def test_bytes_value_decoded(self):
        # bytes -> str(b'...') is acceptable; just must not raise.
        result = safe_str(b"hello")
        self.assertIn("hello", result)

    def test_inf_float_stringified(self):
        # inf is not NaN, so should pass through str() unchanged.
        result = safe_str(float("inf"))
        self.assertIn("inf", result.lower())

    def test_neg_inf_stringified(self):
        result = safe_str(float("-inf"))
        self.assertIn("inf", result.lower())


class TestCleanFilename(unittest.TestCase):

    def test_control_chars_stripped(self):
        self.assertNotIn("\x00", clean_filename("a\x00b"))
        self.assertNotIn("\x1f", clean_filename("a\x1fb"))
        self.assertEqual(clean_filename("a\x00b"), "ab")

    def test_invalid_path_chars_replaced_with_underscore(self):
        for ch in "/\\:*?\"<>|":
            self.assertNotIn(ch, clean_filename(f"a{ch}b"))

    def test_empty_or_whitespace_falls_back_to_untitled(self):
        self.assertEqual(clean_filename(""), "untitled")
        self.assertEqual(clean_filename("   "), "untitled")

    def test_windows_reserved_names_prefixed_with_underscore(self):
        for reserved in ("CON", "PRN", "AUX", "NUL", "COM1", "LPT9"):
            self.assertTrue(clean_filename(reserved).startswith("_"))

    def test_invalid_names_constant_complete(self):
        self.assertIn("CON", INVALID_NAMES)
        self.assertIn("COM9", INVALID_NAMES)
        self.assertIn("LPT1", INVALID_NAMES)
        self.assertNotIn("COM10", INVALID_NAMES)

    def test_long_name_truncated_to_180_chars(self):
        long_name = "a" * 500
        self.assertEqual(len(clean_filename(long_name)), 180)

    def test_valid_name_unchanged(self):
        self.assertEqual(clean_filename("report_2024"), "report_2024")

    def test_reserved_name_check_is_case_insensitive(self):
        # Stem is uppercased before comparison, so any case of reserved name triggers prefix
        self.assertTrue(clean_filename("CON").startswith("_"))
        self.assertTrue(clean_filename("con").startswith("_"))
        self.assertTrue(clean_filename("Con").startswith("_"))
        self.assertTrue(clean_filename("lpt1").startswith("_"))

    def test_long_cjk_name_char_truncated(self):
        # Character-level truncation: 200 CJK chars → 180 whole chars
        # (no U+FFFD, no silent drop).
        long_cjk = "中" * 200
        result = clean_filename(long_cjk)
        self.assertEqual(len(result), 180)
        for ch in result:
            self.assertNotEqual(ch, "\ufffd")


class TestHtmlToMd(unittest.TestCase):

    def test_simple_paragraph(self):
        self.assertEqual(html_to_md("<p>hello</p>"), "hello")

    def test_heading_becomes_atx(self):
        out = html_to_md("<h1>Title</h1>")
        self.assertEqual(out, "# Title")

    def test_strips_script_and_style(self):
        html = "<p>ok</p><script>alert(1)</script><style>p{}</style><p>bye</p>"
        out = html_to_md(html)
        self.assertNotIn("alert", out)
        self.assertNotIn("p{}", out)
        self.assertIn("ok", out)
        self.assertIn("bye", out)

    def test_table_renders_rows(self):
        html = "<table><tr><th>H</th></tr><tr><td>v</td></tr></table>"
        out = html_to_md(html)
        self.assertIn("H", out)
        self.assertIn("v", out)

    def test_empty_html_returns_empty(self):
        self.assertEqual(html_to_md(""), "")


class TestEscapeMdCell(unittest.TestCase):

    def test_pipe_char_escaped(self):
        self.assertEqual(escape_md_cell("| pipe"), "\\| pipe")
        self.assertEqual(
            escape_md_cell("| a | b |"),
            "\\| a \\| b \\|",
        )

    def test_newline_replaced_with_br(self):
        self.assertEqual(
            escape_md_cell("line1\nline2"),
            "line1<br>line2",
        )

    def test_crlf_normalized_first_by_caller(self):
        # escape_md_cell does NOT itself touch \r\n; the caller is
        # expected to run safe_str first. The contract is: only
        # actual newline (single \n) becomes <br>.
        self.assertEqual(
            escape_md_cell("a\nb"),
            "a<br>b",
        )

    def test_empty_string_passes_through(self):
        self.assertEqual(escape_md_cell(""), "")

    def test_no_md_specials_unchanged(self):
        self.assertEqual(escape_md_cell("plain text"), "plain text")
        self.assertEqual(escape_md_cell('quote"'), 'quote"')

    def test_combined_pipe_and_newline(self):
        self.assertEqual(
            escape_md_cell("| a\nb |"),
            "\\| a<br>b \\|",
        )


class TestDecodeText(unittest.TestCase):
    """External tools (textract/antiword) return bytes in a locale-dependent
    encoding; decode_text must handle UTF-8, GBK/GB18030 and a never-failing
    Latin-1 fallback instead of hardcoding UTF-8.
    """

    def test_utf8_bytes(self):
        self.assertEqual(decode_text("中文内容".encode()), "中文内容")

    def test_gbk_bytes(self):
        self.assertEqual(decode_text("中文内容".encode("gbk")), "中文内容")

    def test_latin1_bytes(self):
        self.assertEqual(decode_text("caf\u00e9".encode("latin-1")), "caf\u00e9")

    def test_ascii_bytes(self):
        self.assertEqual(decode_text(b"plain ascii"), "plain ascii")

    def test_gbk_bytes_with_ascii(self):
        self.assertEqual(
            decode_text("报告 Report".encode("gbk")),
            "报告 Report",
        )

    def test_empty_bytes(self):
        self.assertEqual(decode_text(b""), "")

    def test_invalid_bytes_never_raises(self):
        # Latin-1 fallback can decode anything, so this must never raise.
        result = decode_text(b"\x80\x81\xfe")
        self.assertIsInstance(result, str)


if __name__ == "__main__":
    unittest.main()
