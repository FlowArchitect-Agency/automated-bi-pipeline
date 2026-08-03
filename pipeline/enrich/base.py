"""Enricher interface + shared stats tracking.

The four enrichment operations correspond to the four mart tables:
    classify_tickets   → mart.ticket_classifications
    summarize_reviews  → mart.review_summaries
    detect_anomalies   → mart.revenue_anomalies
    enrich_leads       → mart.lead_enrichments

``EnricherStats`` counts LLM calls and an estimated cost so we can show
honest, per-run economics on the dashboard and PDF. The mock backend always
reports zero calls / zero cost.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import pandas as pd


@dataclass
class EnricherStats:
    """Per-run accounting of enrichment cost and volume."""

    llm_calls: int = 0
    llm_cost_estimate_usd: float = 0.0
    rows_enriched: int = 0
    # Which backend produced these results (mock / nvidia / anthropic / ollama)
    backend: str = "mock"
    model: str | None = None
    # True if we *intended* LLM but fell back to mock (e.g. bad key, timeout)
    fell_back_to_mock: bool = False
    errors: list[str] = field(default_factory=list)

    def add_cost(self, calls: int, usd: float) -> None:
        self.llm_calls += calls
        self.llm_cost_estimate_usd = round(self.llm_cost_estimate_usd + usd, 6)

    def note_error(self, msg: str) -> None:
        self.errors.append(msg)


class Enricher(ABC):
    """Abstract base. All methods are pure: DataFrame in → DataFrame out."""

    backend_name: str = "abstract"
    model_name: str | None = None

    def __init__(self) -> None:
        self.stats = EnricherStats(backend=self.backend_name, model=self.model_name)

    @abstractmethod
    def classify_tickets(self, tickets: pd.DataFrame) -> pd.DataFrame:
        """Return ticket_id, category, sentiment, urgency, confidence, detected_language."""

    @abstractmethod
    def summarize_reviews(self, reviews: pd.DataFrame) -> pd.DataFrame:
        """Return product_id, review_window, n_reviews, avg_rating,
        summary_en, summary_fr, top_themes."""

    @abstractmethod
    def detect_anomalies(self, segment_revenue: pd.DataFrame, *, threshold: float) -> pd.DataFrame:
        """Return anomaly_id, detected_date, dimension, dimension_value, metric,
        observed_value, expected_value, deviation, direction, severity."""

    @abstractmethod
    def enrich_leads(self, leads: pd.DataFrame) -> pd.DataFrame:
        """Return lead_id, company_size_band, lead_score, intent_signals, notes_en, notes_fr."""
