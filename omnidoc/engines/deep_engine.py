"""Deep Engine facade (Word / Excel / legacy .doc).

Wires the ported builders (:mod:`omnidoc.engines.deep`) to the
:class:`EngineInterface` contract. The router picks this engine for the four
depth formats (``.doc`` / ``.docx`` / ``.xls`` / ``.xlsx``); everything else
goes to the MarkItDown Engine. The facade keeps the UI layer decoupled: it
only reads a source path/URL and the flattened config dict and returns a
Markdown string (or a rich :class:`DocumentResult`).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from omnidoc.core.document import Document, DocumentResult
from omnidoc.core.interfaces import EngineInterface

_SUPPORTED = {".docx", ".xls", ".xlsx", ".doc"}
# Dependency that the engine actually needs in order to parse its formats.
_REQUIRED_DEPS = ("mammoth", "docx", "pandas", "openpyxl")


def _ext(source: str) -> str:
    return Path(source).suffix.lower()


def _importable(mod: str) -> bool:
    import importlib.util

    return importlib.util.find_spec(mod) is not None


class DeepEngine(EngineInterface):
    name = "deep"

    def supports(self, source: str) -> bool:
        if "://" in source:
            return False
        return _ext(source) in _SUPPORTED

    def available(self) -> bool:
        return all(_importable(m) for m in _REQUIRED_DEPS)

    # ── EngineInterface: in-memory Markdown ────────────────────

    def convert(self, source: str, config: dict[str, Any]) -> str:
        output_fmt = config.get("output_fmt", "md")
        enhanced = bool(config.get("enhanced_md", False))
        rules = config.get("cleaning_rules")
        sheets: Optional[list[str]] = config.get("sheets")

        ext = _ext(source)
        if ext == ".docx":
            from omnidoc.engines.deep import WordBuilder

            built = WordBuilder().build(source, output_fmt, enhanced, rules)
            return self._export(built["content"], output_fmt)
        if ext in (".xls", ".xlsx"):
            from omnidoc.engines.deep import ExcelBuilder

            built = ExcelBuilder().build(source, output_fmt, enhanced, sheets)
            if not built["sheets"]:
                raise RuntimeError(f"Excel 转换失败： {built['errors']}")
            return self._join(built, output_fmt)
        if ext == ".doc":
            from omnidoc.engines.deep import DocBuilder

            built = DocBuilder().build(source, output_fmt, enhanced)
            return self._export(built["content"], output_fmt)
        raise ValueError(f"Deep Engine 不支持该格式： {ext}")

    # ── EngineInterface: rich result (+ optional file output) ──

    def convert_document(self, source: str, config: dict[str, Any]) -> DocumentResult:
        output_fmt = config.get("output_fmt", "md")
        enhanced = bool(config.get("enhanced_md", False))
        rules = config.get("cleaning_rules")
        sheets: Optional[list[str]] = config.get("sheets")
        output_dir = config.get("output_dir")

        ext = _ext(source)
        try:
            if ext == ".docx":
                from omnidoc.engines.deep import WordBuilder

                built = WordBuilder().build(source, output_fmt, enhanced, rules)
                result = self._result_single(built, output_fmt, source, config, output_dir)
            elif ext in (".xls", ".xlsx"):
                from omnidoc.engines.deep import ExcelBuilder

                built = ExcelBuilder().build(source, output_fmt, enhanced, sheets)
                result = self._result_multi(built, output_fmt, source, config, output_dir)
            elif ext == ".doc":
                from omnidoc.engines.deep import DocBuilder

                built = DocBuilder().build(source, output_fmt, enhanced)
                result = self._result_single(built, output_fmt, source, config, output_dir)
            else:
                raise ValueError(f"Deep Engine 不支持该格式： {ext}")
        except Exception as e:  # noqa: BLE001 - pipeline catches and degrades
            result = DocumentResult(source=source, source_format=ext.lstrip("."), engine=self.name)
            result.add_error(str(e))
            return result

        result.engine = self.name
        result.source_format = ext.lstrip(".")
        return result

    # ── helpers ────────────────────────────────────────────────

    @staticmethod
    def _export(content: Any, output_fmt: str) -> str:
        from omnidoc.engines.deep._exporters import get_exporter

        return get_exporter(output_fmt).export(content)

    def _join(self, built: dict[str, Any], output_fmt: str) -> str:
        if output_fmt == "json":
            import json

            payload = {"source": built["source_name"], "sheets": built["sheets"]}
            return json.dumps(payload, ensure_ascii=False, indent=2)
        parts = [self._export(s["content"], output_fmt) for s in built["sheets"]]
        return "\n\n".join(parts)

    def _result_single(
        self,
        built: dict[str, Any],
        output_fmt: str,
        source: str,
        config: dict[str, Any],
        output_dir: Optional[str],
    ) -> DocumentResult:
        serialized = self._export(built["content"], output_fmt)
        result = DocumentResult(source=source, source_format=_ext(source).lstrip("."), engine=self.name)
        result.markdown = serialized
        result.document = Document(text=serialized)
        result.metadata = dict(built.get("metadata", {}))
        if output_dir:
            result.output_paths = self._write(
                [os.path.join(output_dir, f"{built['stem']}_{built.get('suffix', 'doc')}.{output_fmt}")],
                [serialized],
            )
        return result

    def _result_multi(
        self,
        built: dict[str, Any],
        output_fmt: str,
        source: str,
        config: dict[str, Any],
        output_dir: Optional[str],
    ) -> DocumentResult:
        if not built["sheets"]:
            result = DocumentResult(source=source, source_format=_ext(source).lstrip("."), engine=self.name)
            for sn, err in built["errors"]:
                result.add_error(f"{sn}: {err}")
            return result

        serialized = [self._export(s["content"], output_fmt) for s in built["sheets"]]
        result = DocumentResult(source=source, source_format=_ext(source).lstrip("."), engine=self.name)
        result.markdown = "\n\n".join(serialized)
        result.document = Document(text=result.markdown)
        result.metadata = dict(built.get("metadata", {}))
        result.metadata["sheets"] = [
            {"sheet": s["sheet"], "rows": s["rows"], "cols": s["cols"]} for s in built["sheets"]
        ]
        for sn, err in built["errors"]:
            result.add_warning(f"工作表 {sn} 转换失败： {err}")
        if output_dir:
            paths = [
                os.path.join(output_dir, f"{built['stem']}_{s['sn_clean']}.{output_fmt}")
                for s in built["sheets"]
            ]
            result.output_paths = self._write(paths, serialized)
        return result

    @staticmethod
    def _write(paths: list[str], contents: list[str]) -> list[str]:
        written: list[str] = []
        for path, content in zip(paths, contents):
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            written.append(path)
        return written
