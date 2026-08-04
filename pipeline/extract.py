"""Extract stage — simulate loading 5 disparate sources.

In this portfolio demo, each source is extracted from local CSV files to
simulate fetching from live REST APIs (e.g., Salesforce, Shopify, Zendesk).
The same functions would wrap a real `requests.get()` API call in production;
only the loader body changes. Returns a dataclass bundle so downstream stages
get a stable, typed contract.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .config import Settings, get_settings

# Explicit dtypes per source → predictable transforms & safe SQL loads.
_DTYPES: dict[str, dict[str, str]] = {
    "orders": {
        "order_id": "string", "customer_id": "string", "channel": "category",
        "region": "category", "currency": "string",
    },
    "support_tickets": {
        "ticket_id": "string", "customer_id": "string", "channel": "category",
        "language": "category", "status": "category",
    },
    "product_reviews": {
        "review_id": "string", "product_id": "string", "product_name": "string",
        "language": "category",
    },
    "web_analytics": {
        "page_path": "string", "country": "category", "device": "category",
    },
    "crm_leads": {
        "lead_id": "string", "company_name": "string", "industry": "category",
        "region": "category", "source": "category", "status": "category",
    },
}

# Date/timestamp columns parsed by pandas after read.
_DATE_COLS: dict[str, list[str]] = {
    "orders": ["order_date"],
    "support_tickets": ["created_at"],
    "product_reviews": ["created_at"],
    "web_analytics": ["event_date"],
    "crm_leads": ["created_at"],
}


@dataclass(slots=True)
class SourceData:
    """Typed bundle of all 5 extracted sources."""

    orders: pd.DataFrame
    support_tickets: pd.DataFrame
    product_reviews: pd.DataFrame
    web_analytics: pd.DataFrame
    crm_leads: pd.DataFrame

    def total_rows(self) -> int:
        return sum(len(df) for df in self._frames())

    def _frames(self) -> tuple[pd.DataFrame, ...]:
        return (self.orders, self.support_tickets, self.product_reviews,
                self.web_analytics, self.crm_leads)


def _read_csv(name: str, settings: Settings) -> pd.DataFrame:
    path = settings.seed_dir / f"{name}.csv"
    if not path.exists():
        raise FileNotFoundError(f"Seed file not found: {path}")
    df = pd.read_csv(
        path,
        dtype=_DTYPES.get(name, {}),
        parse_dates=_DATE_COLS.get(name, []),
        na_values=["", "NA", "N/A"],
        keep_default_na=True,
    )
    # Validate that the demo watermark exists (guards against accidental
    # real-data drops later).
    readme = settings.seed_dir / "README.md"
    if readme.exists() and "SAMPLE / DEMO" not in readme.read_text(encoding="utf-8"):
        raise RuntimeError("Seed data README missing DEMO watermark — refusing to load.")
    return df


def extract_all(settings: Settings | None = None) -> SourceData:
    """Extract all 5 sources. Raises if any file is missing or malformed."""
    s = settings or get_settings()
    return SourceData(
        orders=_read_csv("orders", s),
        support_tickets=_read_csv("support_tickets", s),
        product_reviews=_read_csv("product_reviews", s),
        web_analytics=_read_csv("web_analytics", s),
        crm_leads=_read_csv("crm_leads", s),
    )
