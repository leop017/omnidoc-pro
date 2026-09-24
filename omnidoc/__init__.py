"""OmniDoc Pro — a one-stop local document pre-processing workbench for RAG.

Deep Word/Excel parsing + MarkItDown breadth + optional LLM enrichment, with a
strictly UI-decoupled core. UI modules (``omnidoc.ui``) are thin shells that
only call the controller; the ``core`` / ``engines`` / ``processors`` packages
never import a UI library.
"""

from omnidoc.controller.conversion import ConversionController, get_controller
from omnidoc.core.config import OmniDocConfig
from omnidoc.core.document import (
    Chunk,
    ConversionStatus,
    Document,
    DocumentResult,
    Element,
)

__version__ = "0.1.9"

__all__ = [
    "OmniDocConfig",
    "Document",
    "DocumentResult",
    "Chunk",
    "Element",
    "ConversionStatus",
    "ConversionController",
    "get_controller",
    "__version__",
]
