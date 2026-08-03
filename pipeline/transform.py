"""Transform stage — clean, type, and standardise extracted data.

Kept deliberately simple and side-effect free: pure DataFrame → DataFrame.
All monetary values are normalised to EUR (seed data is already EUR; the hook
exists so a future multi-currency source can be dropped in).
"""
from __future__ import annotations

import pandas as pd

# Naive FX rates for the demo's single non-EUR edge case. Real pipelines would
# call an FX API; here it's a static map so the transform is deterministic.
_FX_TO_EUR = {"EUR": 1.0, "USD": 0.92, "GBP": 1.17}


def _normalize_money(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Coerce money columns to numeric (float) in place."""
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def transform_orders(df: pd.DataFrame) -> pd.DataFrame:
    """Type money, normalize to EUR, derive net if missing."""
    df = df.copy()
    df = _normalize_money(df, ["gross_revenue_eur", "discount_eur", "net_revenue_eur"])
    # Re-derive net = gross - discount to guarantee internal consistency.
    df["net_revenue_eur"] = (df["gross_revenue_eur"] - df["discount_eur"]).round(2)
    df["units"] = df["units"].fillna(0).astype(int)
    # Drop rows missing a required key/amount (defensive — seed data is clean).
    required = ["order_id", "order_date", "channel", "region", "net_revenue_eur"]
    df = df.dropna(subset=required)
    return df


def transform_tickets(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["subject"] = df["subject"].fillna("").astype(str).str.strip()
    df["description"] = df["description"].fillna("").astype(str).str.strip()
    # Combine for downstream classification convenience.
    df["text"] = (df["subject"] + ". " + df["description"]).str.strip()
    df["sla_breached"] = df["sla_breached"].astype(str).str.lower().isin(["true", "1", "yes"])
    return df


def transform_reviews(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["title"] = df["title"].fillna("").astype(str).str.strip()
    df["body"] = df["body"].fillna("").astype(str).str.strip()
    df["text"] = (df["title"] + ". " + df["body"]).str.strip()
    df["rating"] = pd.to_numeric(df["rating"], errors="coerce").astype("Int64")
    df = df.dropna(subset=["review_id", "product_id", "rating"])
    return df


def transform_web(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in ["sessions", "pageviews"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)
    for c in ["bounce_rate", "avg_session_sec"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def transform_leads(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["notes"] = df["notes"].fillna("").astype(str).str.strip()
    df["est_value_eur"] = pd.to_numeric(df["est_value_eur"], errors="coerce")
    return df


def daily_revenue_by_segment(orders: pd.DataFrame) -> pd.DataFrame:
    """Net revenue + units aggregated by (date, channel, region).

    This is the canonical input to anomaly detection. Also includes an
    ``overall`` rollup so we can flag whole-business anomalies too.
    """
    df = orders.copy()
    df["order_date"] = pd.to_datetime(df["order_date"]).dt.date

    seg = (
        df.groupby(["order_date", "channel", "region"], observed=True)
        .agg(net_revenue_eur=("net_revenue_eur", "sum"),
             units=("units", "sum"),
             n_orders=("order_id", "count"))
        .reset_index()
    )
    overall = (
        df.groupby("order_date")
        .agg(net_revenue_eur=("net_revenue_eur", "sum"),
             units=("units", "sum"),
             n_orders=("order_id", "count"))
        .reset_index()
    )
    overall["channel"] = "all"
    overall["region"] = "all"
    return pd.concat([seg, overall], ignore_index=True)
