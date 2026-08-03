"""AI enrichment layer.

Two interchangeable backends behind a single interface:
    - ``MockEnricher``   : deterministic, offline, zero-cost (default)
    - ``LLMEnricher``    : real LLM calls (NVIDIA NIM / Anthropic / Ollama)

``get_enricher()`` returns the right one based on settings, with safe
fallback to the mock if anything is misconfigured. Every call records its
mode so the dashboard and report always show which backend produced them.
"""
from .base import Enricher, EnricherStats
from .factory import get_enricher

__all__ = ["Enricher", "EnricherStats", "get_enricher"]
