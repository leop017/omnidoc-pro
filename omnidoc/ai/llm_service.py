"""LLM service layer (ported from ``mdgui.llm`` + OmniDoc System Rule #3/#4).

This module is the *only* place that talks to a third-party LLM endpoint.
It is a pure-core component (no UI imports). Two things it guarantees:

* **Graceful degradation (System Rule #3)** — when the LLM is not configured,
  not importable, ``offline_mode`` is set, or a call fails, enrichment is
  skipped and a *warning* is recorded on the :class:`DocumentResult`. The
  plain Markdown the engine already produced is always kept.
* **Concurrency bounding (System Rule #4)** — parallel image-description
  calls are gated by an ``asyncio.Semaphore`` whose size is
  ``LlmSettings.max_concurrency`` (default ``3``), so a batch of images never
  oversubscribes the endpoint.
"""

from __future__ import annotations

import asyncio
import base64
import mimetypes
import os
import re
import time
from typing import Any, Optional

from omnidoc.core.document import Document, DocumentResult
from omnidoc.core.interfaces import EnhancerInterface

DEFAULT_MAX_CONCURRENCY = 3
# Full-form image reference, e.g. ``![alt](url)``. Groupless so that
# :func:`extract_image_refs` (public) keeps returning whole-reference strings.
_IMAGE_REF_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
# Same shape but with the alt text captured, so we can tell whether the
# engine already embedded a description in the alt (PPTX / image sources).
_IMAGE_ALT_RE = re.compile(r"!\[([^\]]*)\]\(([^)]*)\)")


# ── client construction ────────────────────────────────────────

def build_client(llm: dict[str, Any]) -> Optional[Any]:
    """Return an OpenAI-compatible client, or ``None`` when unusable/missing.

    Port of ``mdgui.llm._build_llm_kwargs`` (the client-building half). Requires
    ``enabled`` + ``base_url`` + ``api_key`` + ``model`` and a working
    ``openai`` install; anything else degrades to ``None``.
    """
    if not llm:
        return None
    if not (llm.get("enabled") and llm.get("base_url") and llm.get("api_key") and llm.get("model")):
        return None
    try:
        import openai

        return openai.OpenAI(base_url=llm["base_url"], api_key=llm["api_key"])
    except Exception:  # noqa: BLE001 - degrades to offline
        return None


# ── connectivity probe (port of ``mdgui.llm.on_test_llm``) ────

def test_llm_connection(llm: dict[str, Any]) -> str:
    """Send a minimal chat request and return a human-readable status string."""
    base_url = llm.get("base_url")
    api_key = llm.get("api_key")
    model = llm.get("model")
    if not base_url or not api_key or not model:
        return "❌ 请先填写 Base URL、API Key 和模型名称"
    try:
        import openai

        client = openai.OpenAI(base_url=base_url, api_key=api_key)
        timeout = float(llm.get("timeout", 30.0))
        t0 = time.perf_counter()
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=1,
            timeout=timeout,
        )
        elapsed = time.perf_counter() - t0
        choice = resp.choices[0] if resp.choices else None
        return f"✅ 连接成功 · {elapsed:.1f}s · 模型: {model}" + (
            f"\n响应: {choice.message.content.strip()[:80]}" if choice else ""
        )
    except Exception as e:  # noqa: BLE001 - probe never raises
        return f"❌ 连接失败 · {type(e).__name__}: {e}"


# ── bounded image description (System Rule #4) ─────────────────

def _to_data_uri(ref: str) -> str:
    """Convert a local image path to a ``data:`` URI the vision API can read."""
    if ref.startswith("data:"):
        return ref
    if os.path.exists(ref):
        mime = mimetypes.guess_type(ref)[0] or "image/png"
        with open(ref, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        return f"data:{mime};base64,{b64}"
    return ref  # already an http(s) URL, or unresolvable -> let the call fail


def _describe_one(client: Any, llm: dict[str, Any], ref: str) -> str:
    """Blocking description of a single image (runs inside a worker thread)."""
    prompt = llm.get("prompt") or "请简洁描述这张图片的内容。"
    image_url = _to_data_uri(ref)
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_url}},
            ],
        }
    ]
    resp = client.chat.completions.create(
        model=llm["model"],
        messages=messages,
        timeout=float(llm.get("timeout", 30.0)),
    )
    choice = resp.choices[0] if resp.choices else None
    return (choice.message.content or "").strip() if choice else ""


def extract_image_refs(markdown: str) -> list[str]:
    """Return the raw Markdown image references found in ``markdown``."""
    return _IMAGE_REF_RE.findall(markdown or "")


def _describeable_image_refs(markdown: str) -> list[str]:
    """Return image refs whose alt text is *empty*, in document order.

    These are the only refs worth an LLM description. A non-empty alt
    usually means the producing engine already embedded a description in it
    (MarkItDown fills the alt for PPTX / image sources when it has an LLM
    client), so re-describing would duplicate the LLM call and add a second,
    redundant caption. Empty-alt refs (the common webpage case) still get
    described, preserving the single-source-of-truth behaviour.
    """
    return [
        m.group(0)
        for m in _IMAGE_ALT_RE.finditer(markdown or "")
        if not m.group(1).strip()
    ]


def _run_bounded(client: Any, llm: dict[str, Any], refs: list[str]) -> list[str]:
    """Describe ``refs`` concurrently, gated by an ``asyncio.Semaphore``.

    Each blocking OpenAI call is offloaded to a thread worker
    (``asyncio.to_thread``) so the semaphore genuinely bounds the number of
    in-flight requests.
    """
    max_concurrency = max(1, int(llm.get("max_concurrency", DEFAULT_MAX_CONCURRENCY)))
    sem = asyncio.Semaphore(max_concurrency)

    async def _describe(ref: str) -> str:
        async with sem:
            return await asyncio.to_thread(_describe_one, client, llm, ref)

    results = asyncio.run(asyncio.gather(*(_describe(r) for r in refs), return_exceptions=True))
    return [r if isinstance(r, str) else "" for r in results]


def _apply_descriptions(markdown: str, descs: list[str]) -> str:
    """Append a caption after each *empty-alt* image reference, in order.

    ``descs`` is aligned to the empty-alt refs produced by
    :func:`_describeable_image_refs`; refs that already carry alt text are
    left untouched — their description (if any) came from the engine, so we
    must not add a second one.
    """
    it = iter(descs)

    def _repl(match: re.Match[str]) -> str:
        if match.group(1).strip():
            return match.group(0)
        desc = next(it, "")
        if not desc:
            return match.group(0)
        return f"{match.group(0)}\n\n> 🖼️ 图片描述：{desc}"

    return _IMAGE_ALT_RE.sub(_repl, markdown)


# ── pipeline enhancer (System Rule #3: degrade, never abort) ──

class LlmEnhancer(EnhancerInterface):
    """LLM image-description enhancer wired into the post-processing pipeline.

    ``enhance`` never raises: any configuration / connectivity / per-image
    failure degrades to a warning while preserving the engine's Markdown.
    """

    name = "llm-image"

    def enhance(self, result: DocumentResult, config: dict[str, Any]) -> DocumentResult:
        llm = config.get("llm") or {}
        if bool(config.get("offline_mode", False)) or not llm.get("enabled"):
            result.add_warning("LLM 增强已跳过（offline_mode 或 LLM 未启用）")
            return result
        if not (llm.get("base_url") and llm.get("api_key") and llm.get("model")):
            result.add_warning("LLM 增强已跳过（Base URL / API Key / 模型 配置不完整）")
            return result

        refs = _describeable_image_refs(result.markdown)
        if not refs:
            return result  # nothing to enrich (no image refs, or all already have alt text)

        client = build_client(llm)
        if client is None:
            result.add_warning("LLM 增强已跳过（openai 未安装或初始化失败）")
            return result

        try:
            descs = _run_bounded(client, llm, refs)
            if not any(descs):
                result.add_warning("LLM 图像描述返回为空，保留原始 Markdown")
                return result
            result.markdown = _apply_descriptions(result.markdown, descs)
            result.document = Document(text=result.markdown)
        except Exception as e:  # noqa: BLE001 - LLM is optional enrichment
            result.add_warning(f"LLM 增强失败，保留原始 Markdown： {e}")
        return result


__all__ = [
    "DEFAULT_MAX_CONCURRENCY",
    "LlmEnhancer",
    "build_client",
    "extract_image_refs",
    "test_llm_connection",
]
