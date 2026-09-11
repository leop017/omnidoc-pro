"""Core contracts and data model (no UI imports allowed in this package)."""

from omnidoc.core.config import (
    ChunkingSettings,
    CleaningSettings,
    LlmSettings,
    OmniDocConfig,
)
from omnidoc.core.document import (
    Chunk,
    ConversionStatus,
    Document,
    DocumentResult,
    Element,
)
from omnidoc.core.interfaces import (
    ChunkerInterface,
    CleanerInterface,
    EngineInterface,
    EnhancerInterface,
    ProcessorInterface,
)

__all__ = [
    "OmniDocConfig",
    "LlmSettings",
    "CleaningSettings",
    "ChunkingSettings",
    "Document",
    "DocumentResult",
    "Chunk",
    "Element",
    "ConversionStatus",
    "EngineInterface",
    "ProcessorInterface",
    "CleanerInterface",
    "ChunkerInterface",
    "EnhancerInterface",
]
