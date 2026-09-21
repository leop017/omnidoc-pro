"""Format exporters (ported from ``docconvert.exporters``).

Serialize a builder's raw content object into the requested output format.
The original classes all accepted an ``AppConfig``; the exporters never read
it, so the config argument is dropped here without changing behaviour.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseExporter(ABC):
    @abstractmethod
    def export(self, data: Any) -> str:
        ...


class MarkdownExporter(BaseExporter):
    def export(self, data: Any) -> str:
        if isinstance(data, str):
            return data
        if isinstance(data, dict):
            return data.get("content", str(data))
        return str(data)


class JsonExporter(BaseExporter):
    def export(self, data: Any) -> str:
        if isinstance(data, str):
            return data
        if isinstance(data, dict):
            import json

            return json.dumps(data, ensure_ascii=False, indent=2)
        return str(data)


class HtmlExporter(BaseExporter):
    def export(self, data: Any) -> str:
        if isinstance(data, str):
            return data
        if isinstance(data, dict):
            return data.get("content", str(data))
        return str(data)


def get_exporter(fmt: str) -> BaseExporter:
    if fmt == "html":
        return HtmlExporter()
    if fmt == "md":
        return MarkdownExporter()
    if fmt == "json":
        return JsonExporter()
    raise ValueError(f"不支持的输出格式： {fmt}")
