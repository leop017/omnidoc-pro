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
"""

import unittest
from unittest import mock

from omnidoc.ai import llm_service
from omnidoc.ai.llm_service import (
    LlmEnhancer,
    _apply_descriptions,
    _describeable_image_refs,
    _run_bounded,
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

    ``answers`` maps the *full image ref* (e.g. ``"![](http://i/a.png)"``) ->
    the caption to return. Refs missing from the map yield an empty caption
    (exercises the "some descriptions come back empty" branch).

    Note: the source's ``_describe_one`` passes the full ``ref`` to
    ``_to_data_uri``; for non-local http(s) URLs that returns the ref
    unchanged, so the URL the fake sees is the ref string itself, not the
    bare URL inside the ref.
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


class TestExtractImageRefs(unittest.TestCase):

    def test_finds_all_refs(self):
        md = "a\n![x](http://i/a.png)\nb ![y](http://i/b.png)\n"
        self.assertEqual(extract_image_refs(md), ["![x](http://i/a.png)", "![y](http://i/b.png)"])

    def test_none_when_empty(self):
        self.assertEqual(extract_image_refs(""), [])
        self.assertEqual(extract_image_refs(None), [])


class TestDescribeableImageRefs(unittest.TestCase):

    def test_only_empty_alt_refs_included(self):
        # ``![](url)`` is the empty-alt ref the LLM actually fills in;
        # ``![text](url)`` has its own alt and is treated as already described.
        md = "![text](http://i/a.png)\n![](http://i/b.png)"
        self.assertEqual(_describeable_image_refs(md), ["![](http://i/b.png)"])

    def test_all_have_alt_returns_empty(self):
        md = "![a](http://i/a.png) ![b](http://i/b.png)"
        self.assertEqual(_describeable_image_refs(md), [])

    def test_whitespace_alt_treated_as_empty(self):
        md = "![   ](http://i/a.png)"
        self.assertEqual(_describeable_image_refs(md), ["![   ](http://i/a.png)"])

    def test_single_empty_alt(self):
        md = "![](http://i/a.png)"
        self.assertEqual(_describeable_image_refs(md), ["![](http://i/a.png)"])


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
        client = _ok_client({"![](http://i/a.png)": "A", "![](http://i/b.png)": "B"})
        refs = ["![](http://i/a.png)", "![](http://i/b.png)"]
        descs = _run_bounded(client, _full_llm(), refs)
        self.assertEqual(descs, ["A", "B"])

    def test_failed_ref_yields_empty_string(self):
        client = _ok_client()  # no answers -> empty captions
        refs = ["![](http://i/a.png)"]
        descs = _run_bounded(client, _full_llm(), refs)
        self.assertEqual(descs, [""])

    def test_respects_max_concurrency_floor(self):
        # max_concurrency=0 must be clamped to at least 1, not 0.
        client = _ok_client({"![](http://i/a.png)": "A"})
        descs = _run_bounded(client, _full_llm(max_concurrency=0), ["![](http://i/a.png)"])
        self.assertEqual(descs, ["A"])

    def test_empty_ref_list(self):
        client = _ok_client({"![](http://i/a.png)": "A"})
        self.assertEqual(_run_bounded(client, _full_llm(), []), [])


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
        client = _ok_client({"![](http://i/a.png)": "这是一张图表"})
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
