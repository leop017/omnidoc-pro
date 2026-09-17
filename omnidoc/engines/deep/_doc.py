"""Legacy .doc builder (ported from ``docconvert.converters.doc``).

Uses ``textract`` to extract plain text (an optional heavy dependency) and
wraps it per the requested output format. The algorithm is preserved; only
the file-write step is lifted out into the engine.
"""

from __future__ import annotations

import html as html_mod
from pathlib import Path
from typing import Any

from omnidoc.engines.deep._logger import get_logger
from omnidoc.engines.deep._utils import clean_filename, decode_text, html_to_md


class DocBuilder:
    def __init__(self):
        self.logger = get_logger()

    def build(
        self,
        input_path: str,
        output_fmt: str = "md",
        enhanced_md: bool = False,
    ) -> dict[str, Any]:
        import textract

        self.logger.info("提取文本： %s", input_path)
        raw_bytes = textract.process(input_path)
        text = decode_text(raw_bytes)
        stem = clean_filename(Path(input_path).stem)
        source_name = Path(input_path).name

        if output_fmt == "html":
            content: Any = (
                f'<!DOCTYPE html>\n<html lang="zh-CN">\n<head>\n'
                f'    <meta charset="UTF-8">\n'
                f'    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
                f'    <title>{html_mod.escape(Path(input_path).stem)}</title>\n'
                f'    <style>\n'
                f'        body {{ font-family: "Microsoft YaHei", Arial, sans-serif; margin: 20px; line-height: 1.6; }}\n'
                f'        pre {{ white-space: pre-wrap; word-wrap: break-word; }}\n'
                f'    </style>\n</head>\n<body>\n<pre>\n{html_mod.escape(text)}\n</pre>\n</body>\n</html>'
            )
        elif output_fmt == "md":
            if enhanced_md:
                wrapped = f"<pre>\n{html_mod.escape(text)}\n</pre>"
                content = html_to_md(wrapped)
            else:
                content = text
            content = f"<!-- source: {source_name} | format: doc -->\n\n{content}"
        elif output_fmt == "json":
            content = {"source": source_name, "content": text}
        else:
            raise ValueError(f"不支持的输出格式： {output_fmt}")

        return {
            "content": content,
            "stem": stem,
            "suffix": "doc",
            "metadata": {"source": source_name, "format": "doc", "chars": len(text)},
        }
