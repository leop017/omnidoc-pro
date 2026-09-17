"""AI service layer.

``llm_service`` wraps an OpenAI- / Ollama-compatible endpoint, exposes
``test_llm_connection()`` and the :class:`LlmEnhancer` (bounded image
description, ``asyncio.Semaphore`` default 3), and degrades to offline mode
(skipping image descriptions) when the API is unreachable.
"""

from omnidoc.ai.llm_service import (
    LlmEnhancer,
    build_client,
    extract_image_refs,
    test_llm_connection,
)

__all__ = [
    "LlmEnhancer",
    "build_client",
    "extract_image_refs",
    "test_llm_connection",
]
