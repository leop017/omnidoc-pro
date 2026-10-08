"""Mock tests for :mod:`omnidoc.ai.llm_service` (the third-party LLM seam).

The whole module is exercised without a live OpenAI endpoint: ``build_client``
and ``LlmEnhancer.enhance`` are driven by injecting a fake client through
``mock.patch``, and the concurrency helper ``_run_bounded`` is tested in
isolation. This lifts the previously-uncovered AI layer (was ~24%) into the
rest of the suite, and — incidentally — pins down the async ``_run_bounded``
path that no unit test ever touched before.

Notes on the Markdown image-ref grammar used here:
* ``![](url)``   → empty alt, *describeable* by the LLM
* ``![x](url)``  → non-empty alt, treated as "engine already embedded a
                  description" and left untouched by the enhancer

The vision API receives the *bare* URL (``group(2)``) — never the full
Markdown reference — so http(s) URLs, data URIs and local paths all reach
the endpoint in a readable form.
"""

import os
import tempfile
import unittest
from unittest import mock

from omnidoc.ai import llm_service
from omnidoc.ai.llm_service import (
    LlmEnhancer,
    _api_key_ok,
    _apply_descriptions,
    _describeable_image_refs,
    _placeholder_api_key,
    _run_bounded,
    _sniff_image_mime,
    _to_data_uri,
    build_client,
    extract_image_refs,
)
from omnidoc.core.document import DocumentResult

# ``test_llm_connection`` is a top-level public helper in the source module.
# Importing it as a module-level ``test_*`` name would make pytest try to
# collect it as a test function, so we deliberately access it through the
# ``llm_service`` module attribute instead of a direct import.


def _ok_client(answers: dict | None = None):
    """A fake OpenAI-shaped client whose ``create`` returns canned captions.

    ``answers`` maps the *bare image URL* (e.g. ``"http://i/a.png"``) ->
    the caption to return. URLs missing from the map yield an empty caption
    (exercises the "some descriptions come back empty" branch).

    Note: the source's ``_describe_one`` receives the bare URL extracted from
    the Markdown reference and passes it to ``_to_data_uri``; for non-local
    http(s) URLs that returns the URL unchanged, so the URL the fake sees is
    the bare URL, not the ``![alt](url)`` reference.
    """
    answers = answers or {}

    class _Choice:
        def __init__(self, text):
            self.message = _Message(text)

    class _Message:
        def __init__(self, text):
            self.content = text

    class _Completions:
        def create(self, model, messages, timeout):
            # The "url" here is actually the full ref string (e.g. "![](http://i/a.png)")
            # because _to_data_uri returns the ref unchanged for non-local paths.
            url = messages[0]["content"][1]["image_url"]["url"]
            return mock.Mock(choices=[_Choice(answers.get(url, ""))])

    class _Chat:
        def __init__(self):
            self.completions = _Completions()

    class _FakeClient:
        def __init__(self):
            self.chat = _Chat()

    return _FakeClient()


def _full_llm(**over):
    cfg = {"enabled": True, "base_url": "http://x", "api_key": "k", "model": "m", "max_concurrency": 2}
    cfg.update(over)
    return cfg


class TestApiKeyHelpers(unittest.TestCase):
    """Regression (H1): Ollama's local OpenAI-compatible endpoint accepts any
    api_key (typically a placeholder like "ollama"), so the api_key gate must
    be provider-aware. Raw dicts without a ``provider`` key (tests /
    hand-built configs) default to the historical strict OpenAI behaviour."""

    def test_ollama_without_key_is_ok(self):
        self.assertTrue(_api_key_ok({"provider": "ollama", "base_url": "http://x", "model": "m"}))

    def test_ollama_with_key_is_ok(self):
        self.assertTrue(_api_key_ok({"provider": "ollama", "api_key": "ollama"}))

    def test_openai_style_requires_key(self):
        self.assertFalse(_api_key_ok({"provider": "openai"}))
        self.assertTrue(_api_key_ok({"provider": "openai", "api_key": "sk-x"}))

    def test_raw_dict_defaults_to_strict(self):
        self.assertFalse(_api_key_ok({}))
        self.assertTrue(_api_key_ok({"api_key": "k"}))

    def test_placeholder_fills_ollama_only(self):
        self.assertEqual(_placeholder_api_key({"provider": "ollama"}), "ollama")
        self.assertEqual(_placeholder_api_key({"provider": "ollama", "api_key": ""}), "ollama")
        self.assertEqual(_placeholder_api_key({"provider": "openai", "api_key": "sk-x"}), "sk-x")


class TestBuildClient(unittest.TestCase):

    def test_empty_config_returns_none(self):
        self.assertIsNone(build_client({}))

    def test_missing_fields_return_none(self):
        for llm in ({}, {"enabled": True}, {"enabled": True, "base_url": "u"}):
            self.assertIsNone(build_client(llm), llm)

    def test_full_config_builds_client(self):
        with mock.patch("openai.OpenAI", return_value=object()) as oi:
            client = build_client(_full_llm())
        self.assertIsInstance(client, object)
        oi.assert_called_once()

    def test_openai_import_failure_degrades_to_none(self):
        # A complete config but a broken openai import must not raise.
        with mock.patch.dict("sys.modules", {"openai": None}):
            self.assertIsNone(build_client(_full_llm()))

    def test_ollama_empty_api_key_builds_client(self):
        # Regression (H1): an Ollama provider with an empty api_key must
        # build the client, sending the "ollama" placeholder as the key.
        with mock.patch("openai.OpenAI", return_value=object()) as oi:
            client = build_client(_full_llm(provider="ollama", api_key=""))
        self.assertIsInstance(client, object)
        oi.assert_called_once_with(base_url="http://x", api_key="ollama")

    def test_openai_style_empty_api_key_returns_none(self):
        # Historical strictness preserved for OpenAI-style providers.
        self.assertIsNone(build_client(_full_llm(api_key="")))


class TestExtractImageRefs(unittest.TestCase):

    def test_finds_all_refs(self):
        md = "a\n![x](http://i/a.png)\nb ![y](http://i/b.png)\n"
        self.assertEqual(extract_image_refs(md), ["![x](http://i/a.png)", "![y](http://i/b.png)"])

    def test_none_when_empty(self):
        self.assertEqual(extract_image_refs(""), [])
        self.assertEqual(extract_image_refs(None), [])


class TestDescribeableImageRefs(unittest.TestCase):
    """``_describeable_image_refs`` returns ``(full_ref, bare_url)`` pairs."""

    def test_only_empty_alt_refs_included(self):
        # ``![](url)`` is the empty-alt ref the LLM actually fills in;
        # ``![text](url)`` has its own alt and is treated as already described.
        md = "![text](http://i/a.png)\n![](http://i/b.png)"
        self.assertEqual(
            _describeable_image_refs(md), [("![](http://i/b.png)", "http://i/b.png")]
        )

    def test_all_have_alt_returns_empty(self):
        md = "![a](http://i/a.png) ![b](http://i/b.png)"
        self.assertEqual(_describeable_image_refs(md), [])

    def test_whitespace_alt_treated_as_empty(self):
        md = "![   ](http://i/a.png)"
        self.assertEqual(
            _describeable_image_refs(md), [("![   ](http://i/a.png)", "http://i/a.png")]
        )

    def test_single_empty_alt(self):
        md = "![](http://i/a.png)"
        self.assertEqual(
            _describeable_image_refs(md), [("![](http://i/a.png)", "http://i/a.png")]
        )

    def test_bare_url_extracted_not_full_ref(self):
        # H2 regression: the vision API must receive the bare URL inside the
        # parentheses, never the full Markdown reference (which is not a
        # valid image_url value).
        md = "![](https://example.com/pic.png)"
        (full_ref, url) = _describeable_image_refs(md)[0]
        self.assertEqual(full_ref, "![](https://example.com/pic.png)")
        self.assertEqual(url, "https://example.com/pic.png")
        self.assertFalse(url.startswith("!["))

    def test_trailing_title_stripped_to_bare_url(self):
        # Regression (M3): a CommonMark title ``![alt](url "title")`` used to
        # leak the title into the URL fed to the vision API. The quoted title
        # must be stripped so the API receives the bare URL. (A title that
        # itself embeds a ``)`` is a separate, known limitation of
        # ``_IMAGE_ALT_RE`` and is out of scope here.)
        md = '![](https://example.com/pic.png "the title text")'
        (full_ref, url) = _describeable_image_refs(md)[0]
        self.assertEqual(url, "https://example.com/pic.png")

    def test_single_quoted_title_stripped(self):
        # single-quoted title is stripped to the bare URL; exercise the helper
        # directly (a non-empty alt is not describable).
        from omnidoc.ai.llm_service import _bare_image_url

        self.assertEqual(_bare_image_url("https://example.com/pic.png 'single quoted'"),
                         "https://example.com/pic.png")

    def test_angle_bracket_url_unwrapped(self):
        # Regression (M3): a URL wrapped in angle brackets
        # ``![alt](<url with spaces>)`` must be unwrapped to the bare URL.
        refs = _describeable_image_refs("![x](https://example.com/a) "
                                        "![]( <https://example.com/sp ace.png> )")
        # The empty-alt angle-bracket ref resolves to the unwrapped URL.
        self.assertEqual(refs[0][1], "https://example.com/sp ace.png")

    def test_bare_image_url_no_title_unchanged(self):
        # A plain bare URL (no title, no brackets) passes through untouched.
        from omnidoc.ai.llm_service import _bare_image_url

        self.assertEqual(_bare_image_url("https://example.com/p.png"),
                         "https://example.com/p.png")


class TestApplyDescriptions(unittest.TestCase):

    def test_appends_caption_to_empty_alt_refs_in_order(self):
        # Two empty-alt refs, each gets its own caption, in document order.
        md = "![](http://i/a.png)\n\n![](http://i/b.png)"
        out = _apply_descriptions(md, ["desc-a", "desc-b"])
        self.assertIn("> 🖼️ 图片描述：desc-a", out)
        self.assertIn("> 🖼️ 图片描述：desc-b", out)
        self.assertLess(out.index("desc-a"), out.index("desc-b"))

    def test_refs_with_alt_text_left_untouched(self):
        md = "![already](http://i/a.png)"
        out = _apply_descriptions(md, ["should-not-show"])
        self.assertEqual(out, md)

    def test_empty_caption_leaves_ref_unchanged(self):
        md = "![](http://i/a.png)"
        out = _apply_descriptions(md, [""])
        self.assertEqual(out, md)


class TestRunBounded(unittest.TestCase):

    def test_returns_aligned_captions(self):
        client = _ok_client({"http://i/a.png": "A", "http://i/b.png": "B"})
        refs = [
            ("![](http://i/a.png)", "http://i/a.png"),
            ("![](http://i/b.png)", "http://i/b.png"),
        ]
        descs, failures = _run_bounded(client, _full_llm(), refs)
        self.assertEqual(descs, ["A", "B"])
        self.assertEqual(failures, [])

    def test_empty_caption_not_reported_as_failure(self):
        # A legitimate empty caption (the API answered) is not a failure.
        client = _ok_client()  # no answers -> empty captions
        descs, failures = _run_bounded(
            client, _full_llm(), [("![](http://i/a.png)", "http://i/a.png")]
        )
        self.assertEqual(descs, [""])
        self.assertEqual(failures, [])

    def test_failed_call_collected_with_reason(self):
        fake = mock.Mock()
        fake.chat.completions.create.side_effect = RuntimeError("boom")
        descs, failures = _run_bounded(
            fake, _full_llm(), [("![](http://i/a.png)", "http://i/a.png")]
        )
        self.assertEqual(descs, [""])
        self.assertEqual(len(failures), 1)
        self.assertIn("http://i/a.png", failures[0])
        self.assertIn("RuntimeError", failures[0])

    def test_respects_max_concurrency_floor(self):
        # max_concurrency=0 must be clamped to at least 1, not 0.
        client = _ok_client({"http://i/a.png": "A"})
        descs, _ = _run_bounded(
            client, _full_llm(max_concurrency=0), [("![](http://i/a.png)", "http://i/a.png")]
        )
        self.assertEqual(descs, ["A"])

    def test_empty_ref_list(self):
        client = _ok_client({"http://i/a.png": "A"})
        self.assertEqual(_run_bounded(client, _full_llm(), []), ([], []))


class TestToDataUri(unittest.TestCase):

    def test_passthrough_for_data_uri(self):
        self.assertEqual(_to_data_uri("data:image/png;base64,AAA"), "data:image/png;base64,AAA")

    def test_passthrough_for_url(self):
        self.assertEqual(_to_data_uri("http://x/i.png"), "http://x/i.png")

    def test_local_file_becomes_data_uri(self):
        with mock.patch("os.path.exists", return_value=True), \
             mock.patch("mimetypes.guess_type", return_value=("image/png", None)), \
             mock.patch("builtins.open", mock.mock_open(read_data=b"\x89PNG")):
            out = _to_data_uri("/tmp/img.png")
        self.assertTrue(out.startswith("data:image/png;base64,"))


class TestToDataUriSniffing(unittest.TestCase):
    """Regression (H3): unknown/absent extensions used to fall back to
    ``image/png`` and inline non-image garbage. Magic-byte sniffing must
    inline real images with unknown extensions while passing non-images
    through untouched."""

    PNG = b"\x89PNG\r\n\x1a\n" + b"rest-of-image"

    @staticmethod
    def _write(tmp, name, payload):
        p = os.path.join(tmp, name)
        with open(p, "wb") as f:
            f.write(payload)
        return p

    def test_unknown_extension_real_png_inlined(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._write(tmp, "img.xyz", self.PNG)
            out = _to_data_uri(p)
        self.assertTrue(out.startswith("data:image/png;base64,"))

    def test_unknown_extension_non_image_passthrough(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._write(tmp, "blob.xyz", b"not an image at all")
            self.assertEqual(_to_data_uri(p), p)

    def test_extensionless_real_png_inlined(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._write(tmp, "img", self.PNG)
            out = _to_data_uri(p)
        self.assertTrue(out.startswith("data:image/png;base64,"))

    def test_extensionless_non_image_passthrough(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._write(tmp, "blob", b"random bytes")
            self.assertEqual(_to_data_uri(p), p)

    def test_known_text_extension_still_passthrough(self):
        # A known non-image MIME short-circuits before sniffing — even a
        # .txt file carrying image magic bytes must pass through.
        with tempfile.TemporaryDirectory() as tmp:
            p = self._write(tmp, "note.txt", self.PNG)
            self.assertEqual(_to_data_uri(p), p)

    def test_sniffed_mime_variants(self):
        cases = [
            ("a.png", b"\x89PNG\r\n\x1a\nrest", "image/png"),
            ("a.jpg", b"\xff\xd8\xff\xe0rest", "image/jpeg"),
            ("a.gif", b"GIF89arest", "image/gif"),
            ("a.bmp", b"BM\x00rest", "image/bmp"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            for name, payload, expected in cases:
                p = self._write(tmp, name, payload)
                self.assertEqual(_sniff_image_mime(p), expected, name)
            # WEBP needs the RIFF box plus the WEBP tag at offsets 8-12.
            p = self._write(tmp, "a.webp", b"RIFF\x00\x00\x00\x00WEBPVP8")
            self.assertEqual(_sniff_image_mime(p), "image/webp")

    def test_sniff_missing_file_returns_none(self):
        self.assertIsNone(_sniff_image_mime("Z:/definitely/not/there.png"))


class TestLlmConnectionProbe(unittest.TestCase):
    """``test_llm_connection`` is a top-level function in the source module, so
    we call it directly here rather than as a pytest test function name — the
    latter would collide with pytest's fixture resolution."""

    def test_missing_fields_return_hint(self):
        msg = llm_service.test_llm_connection({"base_url": "u"})
        self.assertIn("请先填写", msg)

    def test_probe_success_via_fake_client(self):
        fake = mock.Mock()
        fake.chat.completions.create.return_value.choices = [
            mock.Mock(message=mock.Mock(content=" hi there\n"))
        ]
        with mock.patch("openai.OpenAI", return_value=fake):
            msg = llm_service.test_llm_connection(_full_llm())
        self.assertIn("连接成功", msg)
        self.assertIn("hi there", msg)

    def test_probe_failure_returns_error(self):
        fake = mock.Mock()
        fake.chat.completions.create.side_effect = RuntimeError("boom")
        with mock.patch("openai.OpenAI", return_value=fake):
            msg = llm_service.test_llm_connection(_full_llm())
        self.assertIn("连接失败", msg)
        self.assertIn("boom", msg)

    def test_probe_ollama_empty_api_key_succeeds(self):
        # Regression (H1): the probe must run (not bail out with the
        # 请先填写 hint) when an Ollama provider leaves the api_key empty.
        fake = mock.Mock()
        fake.chat.completions.create.return_value.choices = [
            mock.Mock(message=mock.Mock(content=" pong\n"))
        ]
        with mock.patch("openai.OpenAI", return_value=fake):
            msg = llm_service.test_llm_connection(_full_llm(provider="ollama", api_key=""))
        self.assertIn("连接成功", msg)
        self.assertIn("pong", msg)

    def test_probe_openai_style_empty_api_key_returns_hint(self):
        msg = llm_service.test_llm_connection(_full_llm(api_key=""))
        self.assertIn("请先填写", msg)


class TestLlmEnhancerEnhance(unittest.TestCase):

    def setUp(self):
        self.enh = LlmEnhancer()

    def _result(self, markdown):
        r = DocumentResult(source="s", markdown=markdown)
        r.document.text = markdown
        return r

    def test_offline_mode_skips(self):
        r = self._result("![](http://i/a.png)")
        self.enh.enhance(r, {"llm": _full_llm(), "offline_mode": True})
        self.assertTrue(any("offline_mode" in w for w in r.warnings))
        self.assertEqual(r.markdown, "![](http://i/a.png)")

    def test_llm_disabled_skips(self):
        r = self._result("![](http://i/a.png)")
        self.enh.enhance(r, {"llm": _full_llm(enabled=False)})
        self.assertTrue(r.warnings)
        self.assertEqual(r.markdown, "![](http://i/a.png)")

    def test_incomplete_config_skips(self):
        r = self._result("![](http://i/a.png)")
        self.enh.enhance(r, {"llm": {"enabled": True, "model": "m"}})
        self.assertTrue(any("配置不完整" in w for w in r.warnings))

    def test_ollama_empty_api_key_passes_config_gate(self):
        # Regression (H1): an Ollama provider with an empty api_key must pass
        # the 配置不完整 gate (its local endpoint needs no key) and proceed to
        # the client-build path, instead of being skipped outright.
        r = self._result("![](http://i/a.png)")
        with mock.patch.object(llm_service, "build_client", return_value=None):
            out = self.enh.enhance(r, {"llm": _full_llm(provider="ollama", api_key="")})
        self.assertFalse(any("配置不完整" in w for w in out.warnings))
        self.assertTrue(any("openai 未安装" in w for w in out.warnings))

    def test_openai_style_empty_api_key_skips(self):
        r = self._result("![](http://i/a.png)")
        self.enh.enhance(r, {"llm": _full_llm(api_key="")})
        self.assertTrue(any("配置不完整" in w for w in r.warnings))

    def test_no_describable_refs_returns_cleanly(self):
        r = self._result("plain text, no images")
        self.enh.enhance(r, {"llm": _full_llm()})
        self.assertEqual(r.markdown, "plain text, no images")
        self.assertEqual(r.warnings, [])

    def test_already_alt_text_returns_cleanly(self):
        r = self._result("![done](http://i/a.png)")
        self.enh.enhance(r, {"llm": _full_llm()})
        self.assertEqual(r.markdown, "![done](http://i/a.png)")
        self.assertEqual(r.warnings, [])

    def test_success_applies_captions(self):
        r = self._result("![](http://i/a.png)")
        client = _ok_client({"http://i/a.png": "这是一张图表"})
        with mock.patch.object(llm_service, "build_client", return_value=client):
            out = self.enh.enhance(r, {"llm": _full_llm()})
        self.assertIn("🖼️ 图片描述：这是一张图表", out.markdown)
        self.assertEqual(out.warnings, [])

    def test_client_build_failure_degrades(self):
        r = self._result("![](http://i/a.png)")
        with mock.patch.object(llm_service, "build_client", return_value=None):
            out = self.enh.enhance(r, {"llm": _full_llm()})
        self.assertTrue(any("openai 未安装" in w for w in out.warnings))
        self.assertEqual(out.markdown, "![](http://i/a.png)")

    def test_all_empty_descriptions_warn_and_keep_markdown(self):
        r = self._result("![](http://i/a.png)")
        client = _ok_client()  # returns empty captions
        with mock.patch.object(llm_service, "build_client", return_value=client):
            out = self.enh.enhance(r, {"llm": _full_llm()})
        self.assertTrue(any("返回为空" in w for w in out.warnings))
        self.assertEqual(out.markdown, "![](http://i/a.png)")

    def test_all_failed_calls_report_reason_not_empty_hint(self):
        # H2 regression: per-image API failures surface their real reason
        # (401/400/…) instead of the misleading "返回为空" hint.
        r = self._result("![](http://i/a.png)")
        fake = mock.Mock()
        fake.chat.completions.create.side_effect = RuntimeError("401 unauthorized")
        with mock.patch.object(llm_service, "build_client", return_value=fake):
            out = self.enh.enhance(r, {"llm": _full_llm()})
        self.assertTrue(any("全部失败" in w and "401" in w for w in out.warnings))
        self.assertEqual(out.markdown, "![](http://i/a.png)")

    def test_partial_failures_warn_but_captions_still_applied(self):
        r = self._result("![](http://i/a.png)\n\n![](http://i/b.png)")
        client = _ok_client({"http://i/b.png": "B 描述"})

        real_create = client.chat.completions.create

        def _create(model, messages, timeout):
            url = messages[0]["content"][1]["image_url"]["url"]
            if url == "http://i/a.png":
                raise RuntimeError("boom-a")
            return real_create(model, messages, timeout)

        client.chat.completions.create = _create
        with mock.patch.object(llm_service, "build_client", return_value=client):
            out = self.enh.enhance(r, {"llm": _full_llm()})
        self.assertIn("🖼️ 图片描述：B 描述", out.markdown)
        self.assertTrue(any("部分图像描述失败" in w and "boom-a" in w for w in out.warnings))

    def test_bounded_run_exception_degrades(self):
        r = self._result("![](http://i/a.png)")
        with mock.patch.object(llm_service, "build_client", return_value=_ok_client()), \
             mock.patch.object(llm_service, "_run_bounded", side_effect=RuntimeError("boom")):
            out = self.enh.enhance(r, {"llm": _full_llm()})
        self.assertTrue(any("LLM 增强失败" in w for w in out.warnings))
        self.assertEqual(out.markdown, "![](http://i/a.png)")

    def test_enhancer_name_constant(self):
        self.assertEqual(self.enh.name, "llm-image")


if __name__ == "__main__":
    unittest.main()
