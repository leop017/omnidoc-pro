"""Regression tests for P1/P2 zero-risk fixes.

P1: _charset_from_ctype must honor charset="..." (quoted) form per RFC 2616.
P2: _fetch_safe_html must not raise LookupError when the Content-Type
    charset is unknown to CPython codecs.
"""
import unittest
from unittest import mock

from omnidoc.engines import markitdown_engine
from omnidoc.engines.markitdown_engine import _charset_from_ctype, _fetch_safe_html


class TestP1QuotedCharset(unittest.TestCase):
    """P1: RFC 2616 section 4.1.2 allows charset-value as a quoted-string."""

    def test_quoted_double_charset(self):
        self.assertEqual(
            _charset_from_ctype('text/html; charset="gbk"'), "gbk"
        )

    def test_quoted_single_charset(self):
        self.assertEqual(
            _charset_from_ctype("text/html; charset='utf-8'"), "utf-8"
        )

    def test_quoted_with_whitespace(self):
        # RFC 7230/9110: ``token = value`` — whitespace AFTER ``=`` but
        # BEFORE the value is legal; whitespace on BOTH sides is not.
        # Cover the legal ``charset= "gbk"`` form.
        self.assertEqual(
            _charset_from_ctype('text/html; charset= "windows-1252"'),
            "windows-1252",
        )

    def test_existing_bare_still_works(self):
        # Regression guard: bare tokens must keep working after P1 fix.
        self.assertEqual(_charset_from_ctype("text/html; charset=gbk"), "gbk")
        self.assertEqual(_charset_from_ctype("text/html;charset=iso-8859-1"), "iso-8859-1")
        self.assertEqual(_charset_from_ctype("text/html"), "utf-8")
        self.assertEqual(_charset_from_ctype(""), "utf-8")


class TestP2UnknownCharset(unittest.TestCase):
    """P2: unknown codec in Content-Type must not crash the fetch."""

    def _make_resp(self, status=200, headers=None, data=b""):
        class _Resp:
            def __init__(self, status, headers, data):
                self.status = status
                self.headers = headers
                self.data = data

            @property
            def is_redirect(self):
                return self.status in (301, 302, 303)

            @property
            def is_temporary_redirect(self):
                return self.status in (307, 308)

            def raise_for_status(self):
                pass

        return _Resp(status, headers or {}, data)

    def test_unknown_charset_does_not_raise_lookuperror(self):
        """A Content-Type with an unknown charset must degrade gracefully,
        NOT raise LookupError (which would abort the whole URL conversion)."""
        resp = self._make_resp(
            status=200,
            headers={"Content-Type": "text/html; charset=nosuchcodec"},
            data=b"<html>ok</html>",
        )

        with mock.patch.object(
            markitdown_engine, "_resolve_ip",
            lambda _url: [markitdown_engine.ipaddress.ip_address("93.184.216.34")],
        ), mock.patch.object(
            markitdown_engine, "_fetch_via_ip",
            lambda _url, _ip, _t: resp,
        ):
            html = _fetch_safe_html("http://93.184.216.34/x")

        self.assertIn("<html>ok</html>", html)

    def test_valid_charset_still_decodes(self):
        resp = self._make_resp(
            status=200,
            headers={"Content-Type": "text/html; charset=utf-8"},
            data="<html>中文</html>".encode(),
        )
        with mock.patch.object(
            markitdown_engine, "_resolve_ip",
            lambda _url: [markitdown_engine.ipaddress.ip_address("93.184.216.34")],
        ), mock.patch.object(
            markitdown_engine, "_fetch_via_ip",
            lambda _url, _ip, _t: resp,
        ):
            html = _fetch_safe_html("http://93.184.216.34/x")
        self.assertIn("中文", html)


if __name__ == "__main__":
    unittest.main()
