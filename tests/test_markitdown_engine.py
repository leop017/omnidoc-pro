"""Mock tests for :mod:`omnidoc.engines.markitdown_engine` (Phase 5d).

The breadth engine's LLM wiring and MarkItDown import are isolated so the
tests never need a live MarkItDown build: we inject a fake converter class
through the engine's ``_md_class`` hook and drive the SSRF guard by patching
``socket.getaddrinfo``. Everything else (route decisions, safe-URL rules,
LLM kwarg translation, graceful-degradation result shape) is tested directly.
"""

import socket
import unittest
from unittest import mock

import openai

from omnidoc.core.document import ConversionStatus
from omnidoc.engines import markitdown_engine
from omnidoc.engines.markitdown_engine import (
    MarkItDownEngine,
    _build_llm_kwargs,
    _ext,
    _is_safe_url,
)


class _FakeResult:
    def __init__(self, markdown):
        self.markdown = markdown


def _ok_converter():
    class _FakeConverter:
        def __init__(self, enable_plugins=False, **kw):
            self.enable_plugins = enable_plugins
            self.kwargs = kw

        def convert(self, source):
            return _FakeResult(f"MD:{source}")

    return _FakeConverter


def _boom_converter():
    class _BoomConverter:
        def __init__(self, enable_plugins=False, **kw):
            pass

        def convert(self, source):
            raise RuntimeError("boom")

    return _BoomConverter


class TestExt(unittest.TestCase):

    def test_lowercase_extension(self):
        self.assertEqual(_ext("a.pdf"), ".pdf")
        self.assertEqual(_ext("A.DOCX"), ".docx")

    def test_no_extension(self):
        self.assertEqual(_ext("README"), "")


class TestSupports(unittest.TestCase):

    def setUp(self):
        self.engine = MarkItDownEngine()

    def test_urls_always_supported(self):
        self.assertTrue(self.engine.supports("https://example.com/a.pdf"))

    def test_depth_formats_rejected(self):
        for ext in (".doc", ".docx", ".xls", ".xlsx"):
            self.assertFalse(self.engine.supports(f"a{ext}"), ext)

    def test_breadth_formats_supported(self):
        for ext in (".pdf", ".pptx", ".csv", ".html", ".png"):
            self.assertTrue(self.engine.supports(f"a{ext}"), ext)


class TestIsSafeUrl(unittest.TestCase):

    def test_scheme_must_be_http_or_https(self):
        self.assertFalse(_is_safe_url("ftp://example.com/x"))
        self.assertFalse(_is_safe_url("file:///x"))

    def test_loopback_ip_literal_rejected(self):
        self.assertFalse(_is_safe_url("http://127.0.0.1/x"))
        self.assertFalse(_is_safe_url("http://[::1]/x"))

    def test_private_ip_literal_rejected(self):
        for ip in ("10.0.0.1", "192.168.0.1", "172.16.0.1"):
            self.assertFalse(_is_safe_url(f"http://{ip}/"), ip)

    def test_public_ip_literal_allowed(self):
        self.assertTrue(_is_safe_url("http://8.8.8.8/x"))

    def test_hostname_resolving_to_private_rejected(self):
        with mock.patch(
            "socket.getaddrinfo",
            return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.0.1", 80))],
        ):
            self.assertFalse(_is_safe_url("http://internal.example/x"))

    def test_hostname_resolving_to_public_allowed(self):
        with mock.patch(
            "socket.getaddrinfo",
            return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))],
        ):
            self.assertTrue(_is_safe_url("http://public.example/x"))

    def test_unresolvable_hostname_is_safe(self):
        with mock.patch("socket.getaddrinfo", side_effect=socket.gaierror("nope")):
            self.assertTrue(_is_safe_url("http://nowhere.invalid/x"))


class TestBuildLlmKwargs(unittest.TestCase):

    def test_offline_mode_returns_empty(self):
        llm = {"enabled": True, "base_url": "http://x", "api_key": "k", "model": "m"}
        self.assertEqual(_build_llm_kwargs(llm, offline_mode=True), {})

    def test_missing_fields_return_empty(self):
        self.assertEqual(_build_llm_kwargs({}, False), {})
        self.assertEqual(_build_llm_kwargs({"enabled": True}, False), {})

    def test_full_config_builds_client(self):
        llm = {"enabled": True, "base_url": "http://x", "api_key": "k", "model": "m"}
        kwargs = _build_llm_kwargs(llm, offline_mode=False)
        self.assertIsInstance(kwargs["llm_client"], openai.OpenAI)
        self.assertEqual(kwargs["llm_model"], "m")
        self.assertNotIn("llm_prompt", kwargs)

    def test_prompt_forwarded_when_present(self):
        llm = {"enabled": True, "base_url": "http://x", "api_key": "k", "model": "m", "prompt": "p"}
        kwargs = _build_llm_kwargs(llm, offline_mode=False)
        self.assertEqual(kwargs["llm_prompt"], "p")


class TestConvertDocument(unittest.TestCase):

    def test_normal_path_via_injected_converter(self):
        engine = MarkItDownEngine()
        engine._md_class = _ok_converter()
        result = engine.convert_document("a.pdf", {})
        self.assertIs(result.status, ConversionStatus.OK)
        self.assertEqual(result.markdown, "MD:a.pdf")
        self.assertEqual(result.document.text, "MD:a.pdf")
        self.assertTrue(result.success)

    def test_public_url_path(self):
        engine = MarkItDownEngine()
        engine._md_class = _ok_converter()
        result = engine.convert_document("http://8.8.8.8/x", {})
        self.assertIs(result.status, ConversionStatus.OK)
        self.assertEqual(result.markdown, "MD:http://8.8.8.8/x")

    def test_ssrf_blocks_document(self):
        engine = MarkItDownEngine()
        engine._md_class = _ok_converter()
        result = engine.convert_document("http://127.0.0.1/x", {})
        self.assertIs(result.status, ConversionStatus.ERROR)
        self.assertTrue(result.warnings)
        self.assertIn("SSRF", result.warnings[0])
        self.assertTrue(result.markdown.startswith("## ⚠️"))
        self.assertFalse(result.success)

    def test_exception_degrades_to_error(self):
        engine = MarkItDownEngine()
        engine._md_class = _boom_converter()
        result = engine.convert_document("a.pdf", {})
        self.assertIs(result.status, ConversionStatus.ERROR)
        self.assertTrue(result.errors)
        self.assertIn("RuntimeError", result.errors[0])
        self.assertIn("boom", result.errors[0])
        self.assertTrue(result.markdown.startswith("## ⚠️"))

    def test_ssrf_raises_on_convert(self):
        engine = MarkItDownEngine()
        engine._md_class = _ok_converter()
        with self.assertRaises(PermissionError):
            engine.convert("http://127.0.0.1/x", {})


class TestModuleWiring(unittest.TestCase):

    def test_available_reports_installation(self):
        engine = MarkItDownEngine()
        self.assertIsInstance(engine.available(), bool)

    def test_default_engine_name(self):
        self.assertEqual(MarkItDownEngine().name, "markitdown")
        self.assertIsNotNone(markitdown_engine)


if __name__ == "__main__":
    unittest.main()
