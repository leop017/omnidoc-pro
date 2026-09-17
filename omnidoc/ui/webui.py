"""Gradio WebUI — a thin shell that ONLY calls the controller (System Rule #2).

No engine / processor logic lives here; the form fields are folded into an
:class:`OmniDocConfig` and handed to :func:`omnidoc.get_controller`, which
returns fully-degraded :class:`DocumentResult`s. This module requires the
``gui`` extra (``pip install 'omnidoc-pro[gui]'``).
"""

from __future__ import annotations

import threading
import webbrowser

import gradio as gr

from omnidoc.ai import test_llm_connection
from omnidoc.core.config import OmniDocConfig

# Mutable so retries refresh the browser URL.
_server_port = 7860


def _open_web() -> None:
    threading.Thread(
        target=lambda: webbrowser.open(f"http://127.0.0.1:{_server_port}/"), daemon=True
    ).start()


def _on_test_llm(base_url: str, api_key: str, model: str) -> str:
    return test_llm_connection(
        {"enabled": True, "base_url": base_url or "", "api_key": api_key or "", "model": model or "", "timeout": 30.0}
    )


def _build_config(
    output_fmt: str,
    enhanced_md: bool,
    deep_first: bool,
    allow_fallback: bool,
    chunking_enabled: bool,
    chunk_strategy: str,
    chunk_size: int,
    chunk_overlap: int,
    offline_mode: bool,
    llm_enabled: bool,
    llm_base_url: str,
    llm_api_key: str,
    llm_model: str,
    llm_prompt: str,
) -> OmniDocConfig:
    cfg = OmniDocConfig(
        output_fmt=output_fmt,
        enhanced_md=bool(enhanced_md),
        deep_first=bool(deep_first),
        allow_fallback=bool(allow_fallback),
        offline_mode=bool(offline_mode),
    )
    cfg.chunking.enabled = bool(chunking_enabled)
    cfg.chunking.strategy = chunk_strategy
    cfg.chunking.chunk_size = int(chunk_size)
    cfg.chunking.chunk_overlap = int(chunk_overlap)
    cfg.llm.enabled = bool(llm_enabled)
    cfg.llm.base_url = llm_base_url or ""
    cfg.llm.api_key = llm_api_key or ""
    cfg.llm.model = llm_model or ""
    cfg.llm.prompt = llm_prompt or ""
    return cfg


def _on_convert(
    files,
    urls,
    output_fmt,
    enhanced_md,
    deep_first,
    allow_fallback,
    chunking_enabled,
    chunk_strategy,
    chunk_size,
    chunk_overlap,
    offline_mode,
    llm_enabled,
    llm_base_url,
    llm_api_key,
    llm_model,
    llm_prompt,
):
    """Convert every uploaded file / URL via the controller (batch-safe)."""
    from omnidoc import get_controller

    cfg = _build_config(
        output_fmt, enhanced_md, deep_first, allow_fallback,
        chunking_enabled, chunk_strategy, chunk_size, chunk_overlap,
        offline_mode, llm_enabled, llm_base_url, llm_api_key, llm_model, llm_prompt,
    )
    # gr.File(type="filepath") hands the callback plain path *strings*;
    # type="file" hands FileData objects (use .path / .name). Handle both.
    sources: list[str] = []
    for f in (files or []):
        path = f if isinstance(f, str) else (getattr(f, "path", None) or getattr(f, "name", None))
        if path:
            sources.append(path)
    for u in (urls or "").splitlines():
        u = u.strip()
        if u:
            sources.append(u)
    if not sources:
        return "等待上传文档或输入网页 URL…", "就绪", "—"

    results = get_controller().convert_batch(sources, cfg)

    md_parts, status_lines = [], []
    for r in results:
        md_parts.append(f"## {r.source}\n\n{r.markdown}")
        line = f"{r.source} · 引擎={r.engine} · 状态={r.status.value}"
        if r.fallback_used:
            line += "（已降级）"
        if r.warnings:
            line += " · ⚠️ " + " | ".join(r.warnings)
        status_lines.append(line)
    md = "\n\n---\n\n".join(md_parts)
    return md, "\n".join(status_lines), f"{len(results)} 个源"


def build_app() -> gr.Blocks:
    with gr.Blocks(title="OmniDoc Pro", theme=gr.themes.Soft()) as app:
        gr.Markdown(
            "## 📄 OmniDoc Pro\n"
            "本地文档预处理工作台：Word/Excel 深度解析 + MarkItDown 广度解析"
            "（PDF/PPT/图片/音频/HTML/CSV…）+ 网页抓取 + 可选 LLM 图像描述，"
            "输出 RAG 友好的 Markdown / 分块。"
        )
        with gr.Row():
            with gr.Column(scale=1):
                files = gr.File(label="文档（支持多文件）", file_count="multiple", type="filepath")
                urls = gr.Textbox(
                    label="网页 URL（每行一个，可选）",
                    placeholder="https://example.com",
                    lines=2,
                )
                with gr.Accordion("⚙️ 转换选项", open=True):
                    output_fmt = gr.Radio(
                        ["md", "html", "json"],
                        value="md",
                        label="输出格式（html/json 仅对 Word/Excel 生效）",
                    )
                    enhanced_md = gr.Checkbox(False, label="增强 Markdown（经 HTML 构建器）")
                    deep_first = gr.Checkbox(True, label="Word/Excel 优先走深度引擎")
                    allow_fallback = gr.Checkbox(True, label="失败时降级到 MarkItDown")
                    offline_mode = gr.Checkbox(False, label="离线模式（跳过 LLM 增强）")
                    chunking_enabled = gr.Checkbox(False, label="启用 RAG 分块")
                    chunk_strategy = gr.Radio(["fixed", "sentence", "markdown"], value="fixed", label="分块策略")
                    chunk_size = gr.Number(512, label="chunk_size", precision=0)
                    chunk_overlap = gr.Number(64, label="chunk_overlap", precision=0)
                with gr.Accordion("🔗 LLM 图像描述（可选）", open=False):
                    llm_enabled = gr.Checkbox(False, label="使用 LLM 描述图片")
                    llm_base_url = gr.Textbox(placeholder="https://api.openai.com/v1", label="Base URL")
                    llm_api_key = gr.Textbox(placeholder="sk-...", label="API Key", type="password")
                    llm_model = gr.Textbox(placeholder="gpt-4o", label="模型")
                    llm_prompt = gr.Textbox(placeholder="请描述这张图片", label="自定义 Prompt（可选）")
                    with gr.Row():
                        test_btn = gr.Button("测试连接", size="sm", variant="secondary")
                        llm_status = gr.Textbox(interactive=False, label=None)
                    test_btn.click(_on_test_llm, inputs=[llm_base_url, llm_api_key, llm_model], outputs=[llm_status])
                convert_btn = gr.Button("⚡ 开始转换", variant="primary")
            with gr.Column(scale=2):
                md_out = gr.Markdown("等待上传文档或输入网页 URL…", show_copy_button=True)
                status_box = gr.Textbox(interactive=False, label="状态", lines=3)
                count_box = gr.Textbox(interactive=False, label="计数")

        convert_btn.click(
            _on_convert,
            inputs=[files, urls, output_fmt, enhanced_md, deep_first, allow_fallback,
                    chunking_enabled, chunk_strategy, chunk_size, chunk_overlap,
                    offline_mode, llm_enabled, llm_base_url, llm_api_key, llm_model, llm_prompt],
            outputs=[md_out, status_box, count_box],
        )
    return app


def main() -> None:
    global _server_port
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--share", action="store_true")
    args = parser.parse_args()
    _server_port = args.port
    build_app().launch(server_name="127.0.0.1", server_port=args.port, inbrowser=True, share=args.share)


if __name__ == "__main__":
    main()
