"""WebUI download helpers — naming derivation and file collection.

The download feature is presentation-layer serving: engine-written files
(``output_paths``) are reused as-is, and results without them (MarkItDown /
URL fetch) get one UTF-8 Markdown file each, named after the source path /
URL.
"""

import os
import tempfile
import unittest

from omnidoc.core.document import ConversionStatus, DocumentResult
from omnidoc.ui.webui import _download_name, _write_downloads


class TestDownloadName(unittest.TestCase):

    def test_file_path_uses_stem_without_extension(self):
        self.assertEqual(_download_name("C:\\docs\\报告.docx", "md"), "报告.md")

    def test_url_uses_netloc_and_path(self):
        self.assertEqual(
            _download_name("https://example.com/a/b", "md"), "example.com_a_b.md"
        )

    def test_bare_url_keeps_domain(self):
        self.assertEqual(
            _download_name("https://example.com/", "md"), "example.com.md"
        )

    def test_url_file_extension_stripped(self):
        self.assertEqual(
            _download_name("https://example.com/page.html", "md"),
            "example.com_page.md",
        )

    def test_invalid_chars_replaced_with_underscore(self):
        for raw in ("a:b|c", "a/b\\c", 'a"b'):
            result = _download_name(raw, "md")
            self.assertNotIn(":", result)
            self.assertNotIn("|", result)
            self.assertNotIn("/", result)
            self.assertNotIn("\\", result)
            self.assertNotIn('"', result)
            self.assertTrue(result.endswith(".md"))

    def test_empty_falls_back_to_untitled(self):
        self.assertEqual(_download_name("", "md"), "untitled.md")

    def test_cjk_preserved(self):
        self.assertEqual(_download_name("报告", "md"), "报告.md")

    def test_extension_appended(self):
        self.assertEqual(_download_name("report_2024", "json"), "report_2024.json")


class TestWriteDownloads(unittest.TestCase):

    def test_engine_written_paths_reused_as_is(self):
        r = DocumentResult(source="x.docx", engine="deep")
        r.markdown = "# hi"
        r.output_paths = [os.path.join(tempfile.gettempdir(), "engine_out.md")]
        out_dir = tempfile.mkdtemp(prefix="omnidoc_test_")
        self.assertEqual(_write_downloads([r], out_dir), r.output_paths)
        self.assertEqual(os.listdir(out_dir), [])

    def test_markdown_result_gets_one_utf8_file(self):
        r = DocumentResult(source="https://example.com/page", engine="markitdown")
        r.markdown = "# hello world"
        out_dir = tempfile.mkdtemp(prefix="omnidoc_test_")
        paths = _write_downloads([r], out_dir)
        self.assertEqual(len(paths), 1)
        self.assertTrue(paths[0].startswith(out_dir))
        self.assertTrue(paths[0].endswith("example.com_page.md"))
        with open(paths[0], encoding="utf-8") as f:
            self.assertEqual(f.read(), "# hello world")

    def test_failed_result_skipped(self):
        r = DocumentResult(source="x.docx", status=ConversionStatus.ERROR)
        out_dir = tempfile.mkdtemp(prefix="omnidoc_test_")
        self.assertEqual(_write_downloads([r], out_dir), [])
        self.assertEqual(os.listdir(out_dir), [])

    def test_batch_mixed_sources(self):
        deep = DocumentResult(source="a.docx", engine="deep")
        deep.markdown = "# a"
        deep.output_paths = [os.path.join(tempfile.gettempdir(), "a_doc.md")]
        web = DocumentResult(source="https://example.com/", engine="markitdown")
        web.markdown = "# b"
        failed = DocumentResult(source="c.docx", status=ConversionStatus.ERROR)
        out_dir = tempfile.mkdtemp(prefix="omnidoc_test_")
        paths = _write_downloads([deep, web, failed], out_dir)
        self.assertEqual(len(paths), 2)
        self.assertEqual(paths[0], deep.output_paths[0])
        self.assertTrue(paths[1].endswith("example.com.md"))


if __name__ == "__main__":
    unittest.main()
