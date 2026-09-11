"""Optional LLM-driven enrichment (implements :class:`EnhancerInterface`).

The concrete :class:`LlmEnhancer` lives in :mod:`omnidoc.ai.llm_service` (the
AI layer owns third-party LLM calls); re-exported here so the pipeline /
controller can depend on the processors package alone.
"""

from omnidoc.ai.llm_service import LlmEnhancer


def get_enhancer() -> LlmEnhancer:
    """Factory for the LLM image-description enhancer."""
    return LlmEnhancer()


__all__ = ["LlmEnhancer", "get_enhancer"]
