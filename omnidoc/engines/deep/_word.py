"""Word (.docx) builder (ported from ``docconvert.converters.word``).

The file-writing step of the original :class:`WordConverter` is removed; this
builder produces the raw content object plus metadata and leaves serialisation
to the exporter. The parsing pipeline (``mammoth`` + header/footer strip +
:class:`WordMdCleaner`) is preserved algorithm-for-algorithm.
"""

from __future__ import annotations

import html as html_mod
import io
from pathlib import Path
from typing import Any, Optional

from docx import Document as DocxDocument

from omnidoc.engines.deep._logger import get_logger
from omnidoc.engines.deep._utils import clean_filename, html_to_md

# Original default: every cleaning rule active.
_DEFAULT_RULES: dict[str, bool] = {
    "remove_page_numbers": True,
    "remove_duplicate_headers": True,
    "remove_empty_lines": True,
    "normalize_spaces": True,
}


class WordBuilder:
    def __init__(self):
        self.logger = get_logger()

    def build(
        self,
        input_path: str,
        output_fmt: str = "md",
        enhanced_md: bool = False,
        cleaning_rules: Optional[dict[str, bool]] = None,
    ) -> dict[str, Any]:
        rules = cleaning_rules if cleaning_rules is not None else _DEFAULT_RULES

        self.logger.info("读取文档： %s", input_path)
        doc = DocxDocument(input_path)
        self._strip_headers_footers(doc)

        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)
        paragraph_count = len([p for p in doc.paragraphs if p.text.strip()])

        if output_fmt == "html":
            content: Any = self._to_html(buf, input_path)
        elif output_fmt == "md":
            content = self._to_md(buf, input_path, paragraph_count, enhanced_md, rules)
        elif output_fmt == "json":
            content = self._to_json(buf, input_path, paragraph_count)
        else:
            raise ValueError(f"不支持的输出格式： {output_fmt}")

        return {
            "content": content,
            "stem": clean_filename(Path(input_path).stem),
            "suffix": "doc",
            "metadata": {
                "source": Path(input_path).name,
                "format": "docx",
                "paragraphs": paragraph_count,
            },
        }

    @staticmethod
    def _strip_headers_footers(doc: object):
        body_xml = doc.element.body  # type: ignore[attr-defined]
        ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        for sect_pr in body_xml.findall(f".//{ns}sectPr"):
            for child in list(sect_pr):
                tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if tag in ("headerReference", "footerReference"):
                    sect_pr.remove(child)

    def _to_html(self, buf: io.BytesIO, input_path: str) -> str:
        import mammoth

        result = mammoth.convert_to_html(buf)
        content = result.value
        title = Path(input_path).stem
        return (
            f'<!DOCTYPE html>\n<html lang="zh-CN">\n<head>\n'
            f'    <meta charset="UTF-8">\n'
            f'    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
            f'    <title>{html_mod.escape(title)}</title>\n'
            f'    <style>\n'
            f'        body {{ font-family: "Microsoft YaHei", Arial, sans-serif; margin: 20px; line-height: 1.6; }}\n'
            f'        table {{ border-collapse: collapse; width: 100%; }}\n'
            f'        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; white-space: pre-wrap; }}\n'
            f'        img {{ max-width: 100%; }}\n'
            f'    </style>\n</head>\n<body>\n{content}\n</body>\n</html>'
        )

    def _to_md(
        self,
        buf: io.BytesIO,
        input_path: str,
        paragraph_count: int,
        enhanced_md: bool = False,
        cleaning_rules: Optional[dict[str, bool]] = None,
    ) -> str:
        import mammoth

        from omnidoc.processors.cleaners.word_md import WordMdCleaner

        if enhanced_md:
            result = mammoth.convert_to_html(buf)
            content = html_to_md(result.value)
        else:
            result = mammoth.convert_to_markdown(buf)
            content = result.value

        rules = cleaning_rules if cleaning_rules is not None else _DEFAULT_RULES
        content = WordMdCleaner().clean(content, {"cleaning_rules": rules})

        header = (
            f"<!-- source: {Path(input_path).name}"
            f" | paragraphs: {paragraph_count} -->\n\n"
        )
        return header + content

    def _to_json(self, buf: io.BytesIO, input_path: str, paragraph_count: int) -> dict:
        import mammoth

        result = mammoth.convert_to_html(buf)
        return {
            "metadata": {
                "source": Path(input_path).name,
                "format": "docx",
                "paragraphs": paragraph_count,
            },
            "content": result.value,
        }
