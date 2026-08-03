"""Factory: choose the enricher based on settings, with safe fallback.

Resolution order:
    1. ENRICHMENT_MODE=mock  → MockEnricher
    2. ENRICHMENT_MODE=llm   → try LLMEnricher; if the provider/key is
       missing or the client errors on construction, fall back to Mock
       and mark ``stats.fell_back_to_mock=True``.

The returned object always works — the pipeline never crashes because of a
missing API key. The stats record *why* it fell back.
"""
from __future__ import annotations

import logging

from ..config import Settings, get_settings
from .base import Enricher
from .llm import LLMEnricher
from .mock import MockEnricher

log = logging.getLogger(__name__)


def get_enricher(settings: Settings | None = None) -> Enricher:
    s = settings or get_settings()

    if s.enrichment_mode == "mock":
        log.info("Enrichment mode: MOCK (deterministic, offline, zero-cost)")
        return MockEnricher()

    # mode == llm
    try:
        enricher = LLMEnricher(s)
        log.info("Enrichment mode: LLM (provider=%s, model=%s)", s.llm_provider, enricher.model)
        return enricher
    except Exception as exc:  # noqa: BLE001 — we deliberately catch broadly here
        log.warning(
            "ENRICHMENT_MODE=llm but LLM unavailable (%s). "
            "Falling back to MOCK enricher so the run still completes.", exc
        )
        fallback = MockEnricher()
        fallback.stats.fell_back_to_mock = True
        fallback.stats.backend = f"mock (llm fallback: {s.llm_provider})"
        fallback.stats.note_error(f"LLM construction failed: {exc}")
        return fallback
