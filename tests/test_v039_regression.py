"""Regression tests for v0.3.9 zero-risk fixes.

P1: _bare_image_url must strip the CommonMark title FIRST and then unwrap
    angle brackets, so that ``![alt](<url> "title")`` (the legal CommonMark
    combination of an angle-bracket URL and a quoted title) yields a bare
    URL instead of leaking ``<`` / ``>`` into the URL handed to the vision
    API.

P2: webui._build_config must merge ``offline_mode`` into ``cfg.llm.enabled``
    (``llm.enabled = llm_enabled and not offline_mode``) so the WebUI's
    offline switch aligns with the CLI's ``_resolve_llm`` contract. Without
    the merge, the flat config dict carries ``offline_mode=True`` *and*
    ``llm.enabled=True`` simultaneously — current call sites still skip the
    LLM via the ``offline_mode`` key, but any future downstream gate that
    only reads ``llm.enabled`` would misfire.
"""
import unittest

from omnidoc.ai.llm_service import _bare_image_url, _IMAGE_ALT_RE
from omnidoc.ui.webui import _build_config


class TestP1BareImageUrlAngleBracketWithTitle(unittest.TestCase):
    """P1: angle-bracket URL + CommonMark title combination."""

    def test_angle_bracket_with_title_yields_bare_url(self):
        """``<url> "title"`` must unwrap to ``url`` (no ``<>`` residue)."""
        self.assertEqual(
            _bare_image_url('<https://example.com/a.png> "My Title"'),
            "https://example.com/a.png",
        )

    def test_angle_bracket_with_single_quoted_title(self):
        self.assertEqual(
            _bare_image_url("<https://example.com/a.png> 'single'"),
            "https://example.com/a.png",
        )

    def test_angle_bracket_url_with_space_in_path_still_unwrapped(self):
        # Regression guard: bracket-with-space (no title) keeps working.
        self.assertEqual(
            _bare_image_url(" <https://example.com/sp ace.png> "),
            "https://example.com/sp ace.png",
        )

    def test_trailing_title_stripped_to_bare_url(self):
        # Regression guard: non-bracket URL + title keeps working.
        self.assertEqual(
            _bare_image_url('https://example.com/pic.png "the title text"'),
            "https://example.com/pic.png",
        )

    def test_single_quoted_title_stripped(self):
        self.assertEqual(
            _bare_image_url("https://example.com/pic.png 'single quoted'"),
            "https://example.com/pic.png",
        )

    def test_bare_image_url_no_title_unchanged(self):
        self.assertEqual(
            _bare_image_url("https://example.com/p.png"),
            "https://example.com/p.png",
        )

    def test_via_image_alt_regex_combination(self):
        """End-to-end: _IMAGE_ALT_RE captures the parenthesised group;
        _bare_image_url must recover the bare URL from the combination."""
        ref = '![](<https://example.com/a.png> "My Title")'
        m = _IMAGE_ALT_RE.search(ref)
        self.assertIsNotNone(m)
        self.assertEqual(_bare_image_url(m.group(2)), "https://example.com/a.png")


class TestP2WebuiLlmEnabledMergedWithOfflineMode(unittest.TestCase):
    """P2: WebUI's offline switch must disable llm.enabled, matching CLI."""

    def _cfg(self, **over):
        kwargs = dict(
            output_fmt="md",
            enhanced_md=False,
            deep_first=False,
            allow_fallback=True,
            chunking_enabled=False,
            chunk_strategy="fixed",
            chunk_size=512,
            chunk_overlap=0,
            chunk_max_size=0,
            offline_mode=False,
            llm_enabled=False,
            llm_base_url="",
            llm_api_key="",
            llm_model="",
            llm_prompt="",
            llm_provider="openai",
        )
        kwargs.update(over)
        return _build_config(**kwargs)

    def test_offline_with_llm_on_disables_llm_enabled(self):
        """Regression target: offline=True + llm_enabled=True must yield
        llm.enabled=False (was True before the fix — contract asymmetry
        with CLI's ``_resolve_llm``)."""
        cfg = self._cfg(offline_mode=True, llm_enabled=True)
        self.assertTrue(cfg.offline_mode)
        self.assertFalse(cfg.llm.enabled)

    def test_offline_with_llm_off_stays_disabled(self):
        cfg = self._cfg(offline_mode=True, llm_enabled=False)
        self.assertFalse(cfg.llm.enabled)

    def test_online_with_llm_on_keeps_enabled(self):
        cfg = self._cfg(offline_mode=False, llm_enabled=True)
        self.assertTrue(cfg.llm.enabled)

    def test_online_with_llm_off_stays_disabled(self):
        cfg = self._cfg(offline_mode=False, llm_enabled=False)
        self.assertFalse(cfg.llm.enabled)


if __name__ == "__main__":
    unittest.main()
