"""MarkItDown Engine facade (breadth formats + URL).

Ported from the ``mdgui`` asset. Handles the 15+ breadth formats (PDF, PPTX,
images, audio, HTML, CSV, ...) and http/https URLs. The two red lines it
enforces:

* **SSRF protection** — :func:`_is_safe_url` rejects URLs that resolve to
  private / loopback / link-local / reserved / multicast IPs.
* **Graceful degradation / offline_mode** — when the LLM is not usable or
  ``offline_mode`` is set, image description is skipped but plain Markdown is
  still returned (never a hard failure that aborts the batch).
"""

from __future__ import annotations

import ipaddress
import socket
import time
from typing import Any
from urllib.parse import urlparse

from omnidoc.core.document import Document, DocumentResult
from omnidoc.core.interfaces import EngineInterface

_DEPTH_EXTS = {".docx", ".xls", ".xlsx", ".doc"}


def _ext(source: str) -> str:
    import os

    return os.path.splitext(source)[1].lower()


def _resolve_ip(url: str):
    """Resolve hostname to IP.  Returns list of ipaddress objects or None on failure.

    Checks *all* DNS records, not just the first, so multi-record responses
    (one public + one private A) cannot bypass the SSRF guard.
    """
    try:
        host = urlparse(url).hostname
        if not host:
            return None
        try:
            return [ipaddress.ip_address(host)]
        except ValueError:
            pass
        try:
            infos = socket.getaddrinfo(host, None)
            ips = [ipaddress.ip_address(i[4][0]) for i in infos]
            return ips if ips else None
        except Exception:
            return None
    except Exception:
        return None


def _is_private_ip(ip: ipaddress._BaseAddress) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_unspecified
        or ip.is_multicast
    )


def _is_safe_url(url: str) -> bool:
    """Reject URLs that resolve to private / loopback / link-local / reserved IPs.

    Only http:// and https:// schemes are allowed.
    All DNS records are checked; if *any* resolves to a private IP the URL is
    rejected (prevents multi-A-record DNS-rebinding bypass).
    """
    scheme = (urlparse(url).scheme or "").lower()
    if scheme not in ("http", "https"):
        return False
    ips = _resolve_ip(url)
    if ips is None:
        return True  # unresolvable -> let the fetch itself fail with a clear error
    return not any(_is_private_ip(ip) for ip in ips)


def _build_llm_kwargs(llm: dict[str, Any], offline_mode: bool) -> dict[str, Any]:
    """Translate the ``llm`` config dict into MarkItDown constructor kwargs.

    Port of ``mdgui.llm._build_llm_kwargs``. No-op when the LLM is not usable
    or ``offline_mode`` is set (graceful degradation: we still convert, just
    without LLM image description).
    """
    kwargs: dict[str, Any] = {}
    if not llm or offline_mode:
        return kwargs
    if llm.get("enabled") and llm.get("base_url") and llm.get("api_key") and llm.get("model"):
        try:
            import openai

            kwargs["llm_client"] = openai.OpenAI(
                base_url=llm["base_url"],
                api_key=llm["api_key"],
            )
            kwargs["llm_model"] = llm["model"]
            if llm.get("prompt"):
                kwargs["llm_prompt"] = llm["prompt"]
        except Exception:
            kwargs = {}
    return kwargs


class MarkItDownEngine(EngineInterface):
    name = "markitdown"

    def __init__(self, **_):
        self._md_class = None

    def _ensure(self):
        if self._md_class is None:
            from markitdown import MarkItDown  # noqa: F401

            self._md_class = MarkItDown
        return self._md_class

    def supports(self, source: str) -> bool:
        # Breadth catch-all: URLs and any file that is not a depth format.
        if "://" in source:
            return True
        return _ext(source) not in _DEPTH_EXTS

    def available(self) -> bool:
        import importlib.util

        return importlib.util.find_spec("markitdown") is not None

    def _convert(self, source: str, config: dict[str, Any]) -> str:
        MarkItDown = self._ensure()
        llm_kwargs = _build_llm_kwargs(config.get("llm", {}), config.get("offline_mode", False))
        enable_plugins = bool(config.get("enable_plugins", False))
        md = MarkItDown(enable_plugins=enable_plugins, **llm_kwargs)
        result = md.convert(source)
        return result.markdown if result else ""

    def convert(self, source: str, config: dict[str, Any]) -> str:
        if "://" in source and not _is_safe_url(source):
            raise PermissionError("已阻止：该地址解析为内网 / 保留 IP（SSRF 防护）")
        return self._convert(source, config)

    def convert_document(self, source: str, config: dict[str, Any]) -> DocumentResult:
        from omnidoc.core.document import ConversionStatus

        result = DocumentResult(source=source, source_format=_ext(source).lstrip(".") or "url", engine=self.name)
        t0 = time.perf_counter()
        try:
            if "://" in source and not _is_safe_url(source):
                result.status = ConversionStatus.ERROR
                result.add_warning("已阻止：该地址解析为内网 / 保留 IP（SSRF 防护）")
                result.markdown = f"## ⚠️ {source}\n\n_已阻止：该地址解析为内网 / 保留 IP（SSRF 防护）_\n"
            else:
                result.markdown = self._convert(source, config)
                result.status = ConversionStatus.OK
            result.document = Document(text=result.markdown)
        except Exception as e:  # noqa: BLE001 - breadth engine already degrades softly
            result.status = ConversionStatus.ERROR
            result.add_error(f"{type(e).__name__}: {e}")
            result.markdown = f"## ⚠️ {source}\n\n_{type(e).__name__}: {e}_\n"
        result.elapsed = time.perf_counter() - t0
        return result
