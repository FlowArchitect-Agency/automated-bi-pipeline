"""Load stage — write raw + mart frames into the warehouse.

Uses pandas ``to_sql`` for simplicity. For the mart tables we replace the
rows of the current run_id first (so re-runs don't pile up duplicates for the
same window). Raw tables are truncated+reloaded each run to mirror a daily
snapshot pattern.
"""
from __future__ import annotations

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from .extract import SourceData
from .transform import (
    daily_revenue_by_segment,
    transform_leads,
    transform_orders,
    transform_reviews,
    transform_tickets,
    transform_web,
)


def load_raw(source: SourceData, engine: Engine, *, schema: str = "raw") -> int:
    """Truncate + reload the 5 raw tables. Returns total rows written."""
    frames = {
        "orders": transform_orders(source.orders),
        "support_tickets": transform_tickets(source.support_tickets),
        "product_reviews": transform_reviews(source.product_reviews),
        "web_analytics": transform_web(source.web_analytics),
        "crm_leads": transform_leads(source.crm_leads),
    }
    total = 0
    with engine.begin() as conn:
        for table in frames:
            conn.execute(text(f"TRUNCATE TABLE {schema}.{table} RESTART IDENTITY CASCADE"))
    for table, df in frames.items():
        # Drop helper columns that aren't in the schema.
        drop = [c for c in ("text",) if c in df.columns]
        if drop:
            df = df.drop(columns=drop)
        df.to_sql(table, engine, schema=schema, if_exists="append", index=False,
                  method="multi", chunksize=2000)
        total += len(df)
    return total


def load_ticket_classifications(df: pd.DataFrame, engine: Engine, run_id: str,
                                *, schema: str = "mart") -> int:
    return _upsert_mart(df, engine, "ticket_classifications", "ticket_id", run_id, schema)


def load_review_summaries(df: pd.DataFrame, engine: Engine, run_id: str,
                          *, schema: str = "mart") -> int:
    return _upsert_mart(df, engine, "review_summaries", ["product_id", "review_window"],
                        run_id, schema)


def load_revenue_anomalies(df: pd.DataFrame, engine: Engine, run_id: str,
                           *, schema: str = "mart") -> int:
    if df.empty:
        return 0
    return _upsert_mart(df, engine, "revenue_anomalies", "anomaly_id", run_id, schema)


def load_lead_enrichments(df: pd.DataFrame, engine: Engine, run_id: str,
                          *, schema: str = "mart") -> int:
    return _upsert_mart(df, engine, "lead_enrichments", "lead_id", run_id, schema)


def _upsert_mart(
    df: pd.DataFrame,
    engine: Engine,
    table: str,
    pk: str | list[str],
    run_id: str,
    schema: str,
) -> int:
    """Insert mart rows, replacing any existing rows for the same PK.

    A simple delete-then-insert upsert. Adequate for the demo's volumes;
    a production system would use INSERT ... ON CONFLICT for atomicity.
    """
    [pk] if isinstance(pk, str) else list(pk)
    if df.empty:
        return 0

    with engine.begin() as conn:
        # For simplicity in this demo, we truncate the table before load.
        # In a real pipeline, we'd use a temp staging table or ON CONFLICT.
        conn.execute(text(f"TRUNCATE TABLE {schema}.{table} CASCADE"))
    
    # psycopg2 cannot adapt lists/dicts automatically. Convert them to JSON strings.
    import json
    for col in df.columns:
        if df[col].apply(lambda x: isinstance(x, (list, dict))).any():
            df[col] = df[col].apply(json.dumps)
            
    df.to_sql(table, engine, schema=schema, if_exists="append", index=False,
              method="multi", chunksize=1000)
    return len(df)


def revenue_segment_frame(orders: pd.DataFrame) -> pd.DataFrame:
    """Convenience wrapper re-exported for the DAG."""
    return daily_revenue_by_segment(orders)


def insert_pipeline_run(engine: Engine, run_id: str, started_at: pd.Timestamp,
                        enrichment_mode: str, llm_provider: str | None,
                        llm_model: str | None) -> None:
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO mart.pipeline_runs "
            "(run_id, started_at, status, enrichment_mode, llm_provider, llm_model) "
            "VALUES (:rid, :st, 'running', :mode, :prov, :model)"
        ), {
            "rid": run_id, "st": started_at.to_pydatetime(),
            "mode": enrichment_mode, "prov": llm_provider, "model": llm_model,
        })


def finalize_pipeline_run(
    engine: Engine,
    run_id: str,
    *,
    finished_at: pd.Timestamp,
    status: str,
    rows_extracted: int,
    rows_enriched: int,
    llm_calls: int,
    llm_cost_estimate: float,
    report_path: str | None,
    slack_sent: bool,
    error: str | None = None,
) -> None:
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE mart.pipeline_runs SET "
            "finished_at=:ft, status=:status, rows_extracted=:re, rows_enriched=:rne, "
            "llm_calls=:calls, llm_cost_estimate=:cost, report_path=:rp, "
            "slack_sent=:ss, error=:err WHERE run_id=:rid"
        ), {
            "rid": run_id, "ft": finished_at.to_pydatetime(), "status": status,
            "re": rows_extracted, "rne": rows_enriched, "calls": llm_calls,
            "cost": llm_cost_estimate, "rp": report_path, "ss": slack_sent, "err": error,
        })
