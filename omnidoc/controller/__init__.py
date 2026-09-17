"""Controller layer — the single entry point the UI/CLI shells call.

- ``router`` — engine router that dispatches by source extension and exposes
  the graceful-degradation chain (Deep -> MarkItDown).
- ``conversion`` — :class:`ConversionController` that chains the router to the
  post-processing pipeline; the only object the UI / CLI is allowed to touch.
"""

from omnidoc.controller.conversion import ConversionController, get_controller
from omnidoc.controller.router import EngineRouter, get_router

__all__ = ["EngineRouter", "get_router", "ConversionController", "get_controller"]
