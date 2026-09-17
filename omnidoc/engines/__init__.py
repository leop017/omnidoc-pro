"""Document-parsing engines.

- ``deep_engine``       — Word/Excel deep parsing (migrated from DocConvert),
                          preserves merged-cell tables, regex cleaning pipeline.
- ``markitdown_engine`` — MarkItDown breadth (PDF/PPT/images/audio/URL,
                          migrated from markitdown-gui), with ``offline_mode``.

Engines are safe to import at package load: both facades defer their heavy
optional dependencies (``markitdown``, ``textract``) to call time, so a
missing optional extra degrades to a warning instead of breaking the package.
"""

from omnidoc.engines.deep_engine import DeepEngine
from omnidoc.engines.markitdown_engine import MarkItDownEngine

__all__ = ["DeepEngine", "MarkItDownEngine"]

