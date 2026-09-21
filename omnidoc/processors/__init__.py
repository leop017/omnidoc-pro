"""Unified post-processing layer (migrated from DocConvert).

- ``cleaners``  — page-number / duplicate-header / whitespace normalisers.
- ``chunkers``  — RAG chunking strategies: ``fixed``, ``sentence``,
                  ``markdown``.
- ``enhancers`` — LLM image-description and metadata extraction.
- :class:`ProcessingPipeline` — cleaner → chunker → enhancer, each stage
  degrading gracefully so one bad file never aborts a batch.
"""

from omnidoc.processors.pipeline import ProcessingPipeline, default_pipeline

__all__ = ["ProcessingPipeline", "default_pipeline"]
