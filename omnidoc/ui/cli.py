"""Typer CLI — a thin shell that ONLY calls the controller (System Rule #2).

Command-line counterpart of the Gradio WebUI: every command folds its flags
into an :class:`OmniDocConfig` and hands it to :func:`omnidoc.get_controller`,
which returns fully-degraded :class:`DocumentResult`s. No engine / processor
logic lives here; the LLM probe delegates to :func:`omnidoc.ai.test_llm_connection`.
Requires the ``cli`` extra (``pip install 'omnidoc-pro[cli]'``).
"""

from __future__ import annotations

import json
import os
import sys
from typing import Optional

from omnidoc import get_controller
from omnidoc.ai import test_llm_connection
from omnidoc.core.config import LlmSettings, OmniDocConfig

try:
    import typer
except ImportError:  # typer is optional (the "cli" extra)
    typer = None  # type: ignore[assignment]

_API_KEY_ENV = "OMNIDOC_LLM_API_KEY"
_BASE_URL_ENV = "OMNIDOC_LLM_BASE_URL"
_MODEL_ENV = "OMNIDOC_LLM_MODEL"


# ── shared helpers (importable without typer) ────────────────────

def _resolve_llm(
    enabled: bool,
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    offline: bool,
) -> LlmSettings:
    """Merge CLI flags with env-var fallbacks into :class:`LlmSettings`."""
    return LlmSettings(
        enabled=enabled and not offline,
        base_url=base_url or os.environ.get(_BASE_URL_ENV, ""),
        api_key=api_key or os.environ.get(_API_KEY_ENV, ""),
        model=model or os.environ.get(_MODEL_ENV, ""),
        prompt=prompt,
    )


def _build_config(
    output_fmt: str,
    enhanced_md: bool,
    deep_first: bool,
    allow_fallback: bool,
    chunking: bool,
    chunk_strategy: str,
    chunk_size: int,
    chunk_overlap: int,
    chunk_max_size: int,
    offline: bool,
    llm_enabled: bool,
    llm_base_url: str,
    llm_api_key: str,
    llm_model: str,
    llm_prompt: str,
) -> OmniDocConfig:
    cfg = OmniDocConfig(
        output_fmt=output_fmt,
        enhanced_md=enhanced_md,
        deep_first=deep_first,
        allow_fallback=allow_fallback,
        offline_mode=offline,
    )
    cfg.chunking.enabled = chunking
    cfg.chunking.strategy = chunk_strategy
    cfg.chunking.chunk_size = chunk_size
    cfg.chunking.chunk_overlap = chunk_overlap
    cfg.chunking.max_chunk_size = chunk_max_size
    cfg.llm = _resolve_llm(llm_enabled, llm_base_url, llm_api_key, llm_model, llm_prompt, offline)
    return cfg


def _render(result, show_chunks: bool) -> str:
    """Human-readable rendering of a single :class:`DocumentResult`."""
    title = f"━━━ {result.source} "
    lines = [title + "━" * max(2, 44 - len(title))]
    status = result.status.value
    if result.fallback_used:
        status += "（已降级）"
    lines.append(f"引擎={result.engine} · 状态={status} · 耗时={result.elapsed:.2f}s")
    for w in result.warnings:
        lines.append(f"⚠️ {w}")
    for e in result.errors:
        lines.append(f"❌ {e}")
    lines.append("")
    lines.append(result.markdown or "（无内容）")
    if show_chunks and result.chunks:
        lines.append("")
        lines.append(f"── 分块（{len(result.chunks)}）──")
        for i, c in enumerate(result.chunks, 1):
            preview = c.text[:200].replace("\n", " ")
            lines.append(f"[{i}] {preview}")
    return "\n".join(lines)


# ── commands ──────────────────────────────────────────────────────

def cmd_convert(
    sources: list[str] = typer.Argument(..., help="文档路径或 URL（可传多个）"),
    output_fmt: str = typer.Option("md", "-f", "--output-fmt", help="输出格式 md/html/json"),
    enhanced_md: bool = typer.Option(False, "--enhanced-md", help="Markdown 经 HTML 构建器增强"),
    no_deep_first: bool = typer.Option(False, "--no-deep-first", help="关闭 Word/Excel 深度优先"),
    no_fallback: bool = typer.Option(False, "--no-fallback", help="关闭深度引擎失败时降级到 MarkItDown"),
    chunk: bool = typer.Option(False, "--chunk", help="启用 RAG 分块"),
    chunk_strategy: str = typer.Option("fixed", "--chunk-strategy", help="fixed/sentence/markdown"),
    chunk_size: int = typer.Option(512, "--chunk-size", help="分块大小（字符）"),
    chunk_overlap: int = typer.Option(64, "--chunk-overlap", help="分块重叠（字符）"),
    chunk_max_size: int = typer.Option(0, "--chunk-max-size", help="markdown 策略下单子树最大字符数，0=不切分"),
    offline: bool = typer.Option(False, "--offline", help="离线模式，跳过 LLM 增强"),
    llm: bool = typer.Option(False, "--llm", help="启用 LLM 图像描述"),
    llm_base_url: str = typer.Option("", "--llm-base-url", help="LLM Base URL（或 env OMNIDOC_LLM_BASE_URL）"),
    llm_api_key: str = typer.Option("", "--llm-api-key", help="LLM API Key（或 env OMNIDOC_LLM_API_KEY）"),
    llm_model: str = typer.Option("", "--llm-model", help="LLM 模型名（或 env OMNIDOC_LLM_MODEL）"),
    llm_prompt: str = typer.Option("", "--llm-prompt", help="自定义图像描述 Prompt"),
    json_out: bool = typer.Option(False, "--json", help="以 JSON 输出全部结果"),
    show_chunks: bool = typer.Option(False, "--show-chunks", help="同时打印分块内容"),
) -> None:
    """把一组文档 / URL 转成 RAG 友好的 Markdown（可选分块 + LLM 图像增强）。"""
    cfg = _build_config(
        output_fmt, enhanced_md, not no_deep_first, not no_fallback,
        chunk, chunk_strategy, chunk_size, chunk_overlap, chunk_max_size,
        offline, llm, llm_base_url, llm_api_key, llm_model, llm_prompt,
    )
    results = get_controller().convert_batch(list(sources), cfg)
    if json_out:
        typer.echo(json.dumps([r.to_dict() for r in results], ensure_ascii=False, indent=2))
    else:
        for i, r in enumerate(results):
            if i:
                typer.echo("")
            typer.echo(_render(r, show_chunks))
    if not any(r.success for r in results):
        raise typer.Exit(code=1)


def cmd_test_llm(
    base_url: str = typer.Option("", "--base-url", help="LLM Base URL（或 env OMNIDOC_LLM_BASE_URL）"),
    api_key: str = typer.Option("", "--api-key", help="LLM API Key（或 env OMNIDOC_LLM_API_KEY）"),
    model: str = typer.Option("", "--model", help="LLM 模型名（或 env OMNIDOC_LLM_MODEL）"),
    timeout: float = typer.Option(30.0, "--timeout", help="连接超时（秒）"),
) -> None:
    """探测 LLM 端点连通性（最小 chat 请求），打印结果。"""
    status = test_llm_connection(
        {
            "enabled": True,
            "base_url": base_url or os.environ.get(_BASE_URL_ENV, ""),
            "api_key": api_key or os.environ.get(_API_KEY_ENV, ""),
            "model": model or os.environ.get(_MODEL_ENV, ""),
            "timeout": timeout,
        }
    )
    typer.echo(status)
    if not status.startswith("✅"):
        raise typer.Exit(code=1)


def cmd_webui(
    port: int = typer.Option(7860, "--port", help="WebUI 端口"),
    share: bool = typer.Option(False, "--share", help="创建 gradio 公开隧道"),
) -> None:
    """启动 Gradio WebUI（薄壳，仅调用 build_app / controller）。"""
    try:
        from omnidoc.ui.webui import build_app
    except ImportError:
        typer.echo("未检测到 Gradio。请安装 GUI 依赖：pip install 'omnidoc-pro[gui]'")
        raise typer.Exit(code=1)
    blocks = build_app()
    typer.echo(f"启动 OmniDoc Pro WebUI：http://127.0.0.1:{port}/")
    blocks.launch(server_name="127.0.0.1", server_port=port, inbrowser=True, share=share)


# ── app assembly (only when typer is available) ──────────────────

if typer is not None:
    app = typer.Typer(
        name="omnidoc",
        help="OmniDoc Pro — 本地文档预处理工作台（RAG 友好的 Markdown / 分块）",
        no_args_is_help=True,
    )
    app.command("convert")(cmd_convert)
    app.command("test-llm")(cmd_test_llm)
    app.command("webui")(cmd_webui)
else:
    app = None  # type: ignore[assignment]


def main() -> Optional[None]:
    """Console-script entry point (``omnidoc`` → ``omnidoc.ui.cli:main``)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(errors="replace")
        except Exception:
            pass
    if app is None:
        print("未检测到 Typer。请安装 CLI 依赖：pip install 'omnidoc-pro[cli]'")
        raise SystemExit(1)
    app()
    return None


if __name__ == "__main__":
    main()
