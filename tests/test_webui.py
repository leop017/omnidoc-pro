"""WebUI download helpers — naming derivation and file collection.

The download feature is presentation-layer serving: engine-written files
(``output_paths``) are reused as-is, and results without them (MarkItDown /
URL fetch) get one UTF-8 Markdown file each, named after the source path /
URL.
"""

import json
import os
import tempfile
import unittest

from omnidoc.core.document import Chunk, ConversionStatus, DocumentResult
from omnidoc.ui.webui import _download_name, _validate_chunking, _write_chunks, _write_downloads


class TestDownloadName(unittest.TestCase):

    def test_file_path_uses_stem_without_extension(self):
        self.assertEqual(_download_name("C:\\docs\\报告.docx", "md"), "报告.md")

    def test_windows_backslash_path_handled_on_any_platform(self):
        self.assertEqual(
            _download_name("C:\\docs\\report final.docx", "md"), "report_final.md"
        )

    def test_posix_path_uses_stem(self):
        self.assertEqual(_download_name("/home/user/报告.docx", "md"), "报告.md")

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


class TestValidateChunking(unittest.TestCase):

    def test_disabled_returns_none(self):
        self.assertIsNone(_validate_chunking(False, "fixed", 0, -1, -5))

    def test_valid_fixed_params(self):
        self.assertIsNone(_validate_chunking(True, "fixed", 512, 64, 0))

    def test_valid_sentence_params(self):
        self.assertIsNone(_validate_chunking(True, "sentence", 256, 32, 999))

    def test_zero_chunk_size_rejected(self):
        msg = _validate_chunking(True, "fixed", 0, 64, 0)
        self.assertIn("chunk_size", msg)

    def test_negative_chunk_size_rejected(self):
        msg = _validate_chunking(True, "sentence", -10, 0, 0)
        self.assertIn("chunk_size", msg)

    def test_overlap_ge_size_rejected(self):
        msg = _validate_chunking(True, "fixed", 64, 64, 0)
        self.assertIn("chunk_overlap", msg)

    def test_negative_overlap_rejected(self):
        msg = _validate_chunking(True, "fixed", 512, -1, 0)
        self.assertIn("chunk_overlap", msg)

    def test_markdown_ignores_size_and_overlap(self):
        self.assertIsNone(_validate_chunking(True, "markdown", 0, 999, 0))

    def test_markdown_negative_max_rejected(self):
        msg = _validate_chunking(True, "markdown", 512, 64, -5)
        self.assertIn("chunk_max_size", msg)

    def test_cleared_number_fields_treated_as_invalid(self):
        msg = _validate_chunking(True, "fixed", None, None, None)
        self.assertIsNotNone(msg)


class TestWriteChunks(unittest.TestCase):

    @staticmethod
    def _chunk(text: str, start: int, end: int, header: str = None) -> Chunk:
        meta = {"chunk_index": 0, "chunk_count": 1}
        if header:
            meta["header"] = header
        return Chunk(text=text, metadata=meta, start_index=start, end_index=end)

    def test_result_with_chunks_gets_jsonl_file(self):
        r = DocumentResult(source="a.docx", engine="deep")
        r.chunks = [self._chunk("hello", 0, 5), self._chunk("world", 6, 11)]
        out_dir = tempfile.mkdtemp(prefix="omnidoc_test_")
        paths = _write_chunks([r], out_dir)
        self.assertEqual(len(paths), 1)
        self.assertTrue(paths[0].endswith("a.chunks.jsonl"))
        with open(paths[0], encoding="utf-8") as f:
            lines = [json.loads(line) for line in f if line.strip()]
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0]["text"], "hello")
        self.assertEqual(lines[0]["source"], "a.docx")
        self.assertEqual(lines[0]["engine"], "deep")
        self.assertEqual(lines[0]["metadata"]["chunk_count"], 1)
        self.assertEqual(lines[1]["start_index"], 6)
        self.assertEqual(lines[1]["end_index"], 11)

    def test_result_without_chunks_skipped(self):
        r = DocumentResult(source="x.docx", status=ConversionStatus.ERROR)
        out_dir = tempfile.mkdtemp(prefix="omnidoc_test_")
        self.assertEqual(_write_chunks([r], out_dir), [])
        self.assertEqual(os.listdir(out_dir), [])

    def test_batch_mixed_sources(self):
        chunked = DocumentResult(source="a.docx", engine="deep")
        chunked.chunks = [self._chunk("body", 0, 4)]
        plain = DocumentResult(source="https://example.com/", engine="markitdown")
        plain.markdown = "# b"
        out_dir = tempfile.mkdtemp(prefix="omnidoc_test_")
        paths = _write_chunks([chunked, plain], out_dir)
        self.assertEqual(len(paths), 1)
        self.assertTrue(paths[0].endswith("a.chunks.jsonl"))

    def test_cjk_source_preserved_in_filename(self):
        r = DocumentResult(source="报告.docx", engine="deep")
        r.chunks = [self._chunk("内容", 0, 2)]
        out_dir = tempfile.mkdtemp(prefix="omnidoc_test_")
        paths = _write_chunks([r], out_dir)
        self.assertTrue(paths[0].endswith("报告.chunks.jsonl"))


if __name__ == "__main__":
    unittest.main()
