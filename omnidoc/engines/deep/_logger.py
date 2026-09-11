"""Shared logger for the Deep Engine (ported from ``docconvert.logger``)."""

from __future__ import annotations

import logging


def get_logger() -> logging.Logger:
    return logging.getLogger("omnidoc.deep")
