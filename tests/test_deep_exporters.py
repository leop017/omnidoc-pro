"""Migrated from ``docconvert`` ``tests/test_exporters.py`` -> ``omnidoc.engines.deep._exporters``.

The ported exporters dropped the unused ``AppConfig`` constructor argument;
the public ``export(data)`` behaviour is unchanged, so the assertions carry
over verbatim.
"""

import json
import unittest

from omnidoc.engines.deep._exporters import (
    BaseExporter,
    HtmlExporter,
    JsonExporter,
    MarkdownExporter,
    get_exporter,
)


class TestGetExporterFactory(unittest.TestCase):

    def test_html_returns_html_exporter(self):
        self.assertIsInstance(get_exporter("html"), HtmlExporter)

    def test_md_returns_markdown_exporter(self):
        self.assertIsInstance(get_exporter("md"), MarkdownExporter)

    def test_json_returns_json_exporter(self):
        self.assertIsInstance(get_exporter("json"), JsonExporter)

    def test_unsupported_format_raises(self):
        with self.assertRaises(ValueError):
            get_exporter("xml")


class TestHtmlExporter(unittest.TestCase):

    def setUp(self):
        self.exporter = HtmlExporter()

    def test_string_passthrough(self):
        self.assertEqual(self.exporter.export("<p>hello</p>"), "<p>hello</p>")

    def test_dict_extracts_content_key(self):
        self.assertEqual(self.exporter.export({"content": "X"}), "X")

    def test_dict_without_content_falls_back_to_str(self):
        result = self.exporter.export({"other": 1})
        self.assertIn("other", result)

    def test_other_types_stringified(self):
        self.assertEqual(self.exporter.export(123), "123")


class TestMarkdownExporter(unittest.TestCase):

    def setUp(self):
        self.exporter = MarkdownExporter()

    def test_string_passthrough(self):
        self.assertEqual(self.exporter.export("# Title"), "# Title")

    def test_dict_extracts_content_key(self):
        self.assertEqual(self.exporter.export({"content": "## H"}), "## H")

    def test_other_types_stringified(self):
        self.assertEqual(self.exporter.export(None), "None")


class TestJsonExporter(unittest.TestCase):

    def setUp(self):
        self.exporter = JsonExporter()

    def test_string_passthrough(self):
        self.assertEqual(self.exporter.export("already a string"), "already a string")

    def test_dict_serialized_to_json(self):
        result = self.exporter.export({"key": "值", "num": 1})
        parsed = json.loads(result)
        self.assertEqual(parsed["key"], "值")
        self.assertEqual(parsed["num"], 1)
        self.assertIn("\n", result, "JSON should be pretty-printed with indent")

    def test_dict_preserves_unicode(self):
        result = self.exporter.export({"中文": "测试"})
        self.assertIn("中文", result)
        self.assertNotIn("\\u", result, "ensure_ascii=False should keep unicode")

    def test_other_types_stringified(self):
        self.assertEqual(self.exporter.export(42), "42")


class TestExporterBaseInterface(unittest.TestCase):

    def test_all_subclasses_inherit_from_base(self):
        for cls in (HtmlExporter, MarkdownExporter, JsonExporter):
            self.assertTrue(issubclass(cls, BaseExporter))


if __name__ == "__main__":
    unittest.main()
