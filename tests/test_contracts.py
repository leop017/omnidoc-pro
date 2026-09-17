"""Phase 1 smoke tests: contracts, data model and config are coherent."""

from __future__ import annotations

import pytest

from omnidoc.core.config import LlmSettings, OmniDocConfig
from omnidoc.core.document import (
    Chunk,
    ConversionStatus,
    Document,
    DocumentResult,
    Element,
)
from omnidoc.core.interfaces import EngineInterface


def test_config_defaults_flatten():
    cfg = OmniDocConfig()
    kwargs = cfg.to_engine_kwargs()
    assert kwargs["output_fmt"] == "md"
    assert kwargs["cleaning_rules"]["remove_page_numbers"] is True
    assert kwargs["llm"]["max_concurrency"] == 3
    # 死配置已移除：to_engine_kwargs 不再导出未消费字段
    assert "excel_read_only" not in kwargs
    assert "pdf_page_size" not in kwargs
    assert "max_rows" not in kwargs


def test_llm_usable_requires_all_parts():
    assert LlmSettings().is_usable() is False
    assert (
        LlmSettings(enabled=True, base_url="http://x", api_key="k", model="m").is_usable()
        is True
    )


def test_document_result_shape():
    doc = Document(text="hi", elements=[Element(element_type="paragraph", text="hi")])
    result = DocumentResult(source="a.md", document=doc)
    assert result.status is ConversionStatus.OK
    assert result.success is False  # nothing produced yet
    result.markdown = "# hi"
    result.chunks = [Chunk(text="hi")]
    assert result.success is True
    payload = result.to_dict()
    assert payload["chunk_count"] == 1
    assert payload["markdown"] == "# hi"
    assert payload["status"] == "ok"


def test_engine_interface_is_abstract():
    with pytest.raises(TypeError):
        EngineInterface()  # type: ignore[call-arg]


def test_minimal_engine_satisfies_contract():
    class _Dummy(EngineInterface):
        name = "dummy"

        def supports(self, source: str) -> bool:
            return True

        def convert(self, source: str, config: dict) -> str:
            return "x"

    assert _Dummy().available() is True
    assert _Dummy().supports("a.md") is True
    res = _Dummy().convert_document("a.md", {})
    assert isinstance(res, DocumentResult)
    assert res.markdown == "x"
    assert res.source_format == "md"
