"""MarkItDown Engine facade (breadth formats + URL).

Ported from the ``mdgui`` asset. Handles the 15+ breadth formats (PDF, PPTX,
images, audio, HTML, CSV, ...) and http/https URLs. The two red lines it
enforces:

* **SSRF protection** — URLs that resolve to private / loopback / link-local
  / reserved / multicast / CGNAT IPs are rejected, redirects are followed
  manually with re-validation at every hop, and the connection is pinned to
  the validated IP (SNI preserved), so neither a redirect nor DNS rebinding
  can route the request to a private address.
* **Graceful degradation / offline_mode** — when the LLM is not usable or
  ``offline_mode`` is set, image description is skipped but plain Markdown is
  still returned (never a hard failure that aborts the batch).
"""

from __future__ import annotations

import io
import ipaddress
import socket
import time
from typing import Any
from urllib.parse import urljoin, urlparse

from omnidoc.ai.llm_service import _api_key_ok, _placeholder_api_key
from omnidoc.core.document import Document, DocumentResult
from omnidoc.core.interfaces import EngineInterface

# The legacy .doc binary format is the only extension MarkItDown cannot
# parse. Depth formats (.docx/.xls/.xlsx) are handled natively by MarkItDown
# and stay claimable here so the router builds a genuine Deep -> MarkItDown
# fallback chain (System Rule #3) and ``deep_first=False`` really routes
# them to this engine.
_UNPARSEABLE_EXTS = {".doc"}
_MAX_REDIRECTS = 10
_FETCH_TIMEOUT = 30.0
# Networks the stdlib ``ipaddress`` flags miss but that must never be
# reachable through a fetched URL.
_EXTRA_PRIVATE_NETS = (
    ipaddress.ip_network("100.64.0.0/10"),  # CGNAT (carrier NAT, Tailscale...)
    ipaddress.ip_network("64:ff9b::/96"),  # NAT64
)
# Binary formats whose MarkItDown "plain-text fallback" output is always
# garbage: when every real converter fails, MarkItDown 0.1.x echoes the raw
# file bytes decoded as text instead of raising.
_BINARY_ECHO_EXTS = {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip"}


def _is_plain_text_echo(source: str, markdown: str) -> bool:
    """True when MarkItDown's built-in plain-text fallback echoed raw bytes.

    When every real converter fails, MarkItDown 0.1.x returns the file's raw
    bytes decoded as text. For binary formats that is garbage output dressed
    up as a conversion success — detect and reject it so the controller
    records a real failure instead of a DEGRADED ``success=True``. Text
    formats (.txt/.csv/...) convert through that same converter legitimately,
    so they are excluded.
    """
    if _ext(source) not in _BINARY_ECHO_EXTS:
        return False
    try:
        from pathlib import Path

        raw = Path(source).read_bytes().decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - unreadable source: let the caller decide
        return False
    return markdown.strip() == raw.strip()


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


def _is_private_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_unspecified
        or ip.is_multicast
    ):
        return True
    return any(ip in net for net in _EXTRA_PRIVATE_NETS)


def _is_safe_url(url: str) -> bool:
    """Reject URLs that resolve to private / loopback / link-local / reserved IPs.

    Only http:// and https:// schemes are allowed.
    All DNS records are checked; if *any* resolves to a private IP the URL is
    rejected (prevents multi-A-record DNS-rebinding bypass). Unresolvable
    hostnames pass here and fail with a clear error at fetch time — the
    authoritative check lives in :func:`_fetch_safe_html`, which re-resolves
    and re-validates every hop before connecting.
    """
    scheme = (urlparse(url).scheme or "").lower()
    if scheme not in ("http", "https"):
        return False
    ips = _resolve_ip(url)
    if ips is None:
        return True  # unresolvable -> let the fetch itself fail with a clear error
    return not any(_is_private_ip(ip) for ip in ips)


def _charset_from_ctype(content_type: str) -> str:
    """Extract charset from a Content-Type header value; default to UTF-8.

    urllib3's ``HTTPHeaderDict`` exposes the raw header string but has no
    ``get_content_charset()`` (that's a ``requests`` API).  We parse the
    ``charset=`` parameter ourselves and fall back to UTF-8, which covers
    the overwhelming majority of web pages.
    """
    import re

    m = re.search(r"charset=([\w-]+)", content_type, re.IGNORECASE)
    if m:
        return m.group(1)
    return "utf-8"


def _fetch_via_ip(url: str, ip: str, timeout: float):
    """GET ``url`` while connecting to the pre-validated ``ip``.

    TLS keeps verifying the original hostname (``server_hostname`` is used
    for SNI *and* certificate matching), so the pin never downgrades
    certificate checks. Redirects are never followed automatically — the
    caller re-validates each hop before following it.
    """
    import urllib3

    parsed = urlparse(url)
    is_https = parsed.scheme == "https"
    port = parsed.port or (443 if is_https else 80)
    target = parsed.path or "/"
    if parsed.query:
        target = f"{target}?{parsed.query}"
    headers = {"Host": parsed.netloc, "User-Agent": "omnidoc/0.2", "Accept": "*/*"}
    pool_kwargs: dict[str, Any] = {
        "timeout": urllib3.Timeout(connect=timeout, read=timeout),
        "retries": False,
    }
    # HTTPSConnectionPool subclasses HTTPConnectionPool, so the wider type
    # covers both branches.
    pool: urllib3.HTTPConnectionPool
    if is_https:
        pool = urllib3.HTTPSConnectionPool(
            ip, port, server_hostname=parsed.hostname, **pool_kwargs
        )
    else:
        pool = urllib3.HTTPConnectionPool(ip, port, **pool_kwargs)
    try:
        return pool.urlopen("GET", target, headers=headers, redirect=False, preload_content=True)
    finally:
        pool.close()


def _fetch_safe_html(url: str, timeout: float = _FETCH_TIMEOUT) -> str:
    """Fetch a URL's content with full SSRF protection; return the raw HTML.

    Every hop is resolved, validated against the private-IP guard and pinned
    to the validated IP *before* connecting (closing the DNS-rebinding
    TOCTOU window); redirects are followed manually with re-validation at
    every hop.  The scheme is re-checked per hop as well: only ``http``/``https``
    are allowed, so a redirect to e.g. ``ftp://`` is rejected (the engine can
    only feed http/https HTML to the converter anyway).  Raises
    ``PermissionError`` when a hop resolves to a private IP, ``ValueError`` on
    an unresolvable hostname, a non-http(s) scheme, or too many redirects.
    """
    current = url
    for _ in range(_MAX_REDIRECTS + 1):
        if urlparse(current).scheme not in ("http", "https"):
            raise ValueError(f"仅允许 http/https： {urlparse(current).scheme or current}")
        ips = _resolve_ip(current)
        if not ips:
            raise ValueError(f"无法解析主机名： {urlparse(current).hostname or current}")
        bad = [ip for ip in ips if _is_private_ip(ip)]
        if bad:
            raise PermissionError("已阻止：重定向目标解析为内网 / 保留 IP（SSRF 防护）")
        resp = _fetch_via_ip(current, str(ips[0]), timeout)
        if resp.is_redirect or resp.is_temporary_redirect:
            location = resp.headers.get("Location", "")
            if not location:
                raise ValueError("重定向缺少 Location 头")
            current = urljoin(current, location)
            continue
        resp.raise_for_status()
        charset = _charset_from_ctype(resp.headers.get("Content-Type", ""))
        return resp.data.decode(charset, errors="replace")
    raise ValueError(f"重定向次数超过 {_MAX_REDIRECTS}")


def _build_llm_kwargs(llm: dict[str, Any], offline_mode: bool) -> dict[str, Any]:
    """Translate the ``llm`` config dict into MarkItDown constructor kwargs.

    Port of ``mdgui.llm._build_llm_kwargs``. No-op when the LLM is not usable
    or ``offline_mode`` is set (graceful degradation: we still convert, just
    without LLM image description).
    """
    kwargs: dict[str, Any] = {}
    if not llm or offline_mode:
        return kwargs
    if llm.get("enabled") and llm.get("base_url") and llm.get("model") and _api_key_ok(llm):
        try:
            import openai

            kwargs["llm_client"] = openai.OpenAI(
                base_url=llm["base_url"],
                api_key=_placeholder_api_key(llm),
                timeout=float(llm.get("timeout", 30.0)),
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
        # Breadth catch-all: URLs and any file MarkItDown can parse. Only the
        # legacy .doc binary format is excluded, so depth formats
        # (.docx/.xls/.xlsx) keep a genuine Deep -> MarkItDown fallback chain
        # and ``deep_first=False`` really hands them to this engine.
        if "://" in source:
            return True
        return _ext(source) not in _UNPARSEABLE_EXTS

    def available(self) -> bool:
        import importlib.util

        return importlib.util.find_spec("markitdown") is not None

    def _convert(self, source: str, config: dict[str, Any]) -> str:
        MarkItDown = self._ensure()
        llm_kwargs = _build_llm_kwargs(config.get("llm", {}), config.get("offline_mode", False))
        enable_plugins = bool(config.get("enable_plugins", False))
        md = MarkItDown(enable_plugins=enable_plugins, **llm_kwargs)
        if "://" in source:
            html = _fetch_safe_html(source)
            result = md.convert_stream(
                io.BytesIO(html.encode("utf-8")), file_extension=".html", url=source
            )
            return result.markdown if result else ""
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
                # MarkItDown swallows per-file conversion failures (empty
                # payload) or falls back to echoing the raw binary bytes —
                # both must count as conversion failures, otherwise the
                # controller's fallback logic would treat them as a success
                # and report ``success=True`` (exit 0) for a broken file.
                if result.markdown and not _is_plain_text_echo(source, result.markdown):
                    result.status = ConversionStatus.OK
                else:
                    result.status = ConversionStatus.ERROR
                    result.add_error(
                        "转换结果为空：引擎未能解析该文件"
                        if not result.markdown
                        else "转换结果为原始文件回显：所有转换器均失败（文件可能已损坏）"
                    )
            result.document = Document(text=result.markdown)
        except Exception as e:  # noqa: BLE001 - breadth engine already degrades softly
            result.status = ConversionStatus.ERROR
            result.add_error(f"{type(e).__name__}: {e}")
            result.markdown = f"## ⚠️ {source}\n\n_{type(e).__name__}: {e}_\n"
        result.elapsed = time.perf_counter() - t0
        return result
