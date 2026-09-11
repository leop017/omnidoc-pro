"""Deep Engine internals (Word / Excel / legacy .doc).

Ported from the DocConvert asset and refactored to *build content* rather than
write files, so :class:`omnidoc.engines.deep_engine.DeepEngine` can decide
whether to serialise in-memory or persist to ``output_dir``.
"""

from omnidoc.engines.deep._doc import DocBuilder
from omnidoc.engines.deep._excel import ExcelBuilder
from omnidoc.engines.deep._models import MergeInfo, ProgressEvent
from omnidoc.engines.deep._word import WordBuilder

__all__ = [
    "DocBuilder",
    "ExcelBuilder",
    "MergeInfo",
    "ProgressEvent",
    "WordBuilder",
]
