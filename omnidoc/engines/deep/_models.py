"""Data models for the Deep Engine (ported from ``docconvert.models``).

``MergeInfo`` is the currency of the Excel merged-cell algorithm; the
coordinates are 1-based workbook rows/cols and are remapped onto the
post-``dropna`` rendered table by :mod:`omnidoc.engines.deep._excel`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class MergeInfo:
    rowspan: int = 1
    colspan: int = 1
    is_master: bool = False
    is_merged: bool = False
    min_row: int = 0
    min_col: int = 0
    max_row: int = 0
    max_col: int = 0


@dataclass
class ProgressEvent:
    message: str = ""
    progress: float = 0.0
    done: bool = False
    error: Optional[str] = None
