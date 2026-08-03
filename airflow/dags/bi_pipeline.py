"""Airflow DAG for the Automated BI Pipeline."""
import logging
from datetime import datetime, timedelta
import uuid

import pandas as pd
from airflow import DAG
from airflow.operators.python import PythonOperator

from pipeline.config import get_settings
from pipeline.db import make_engine, wait_for_db, bootstrap_schema
from pipeline.extract import extract_all
from pipeline.load import (
    load_raw,
    revenue_segment_frame,
    insert_pipeline_run,
    finalize_pipeline_run,
    load_ticket_classifications,
    load_review_summaries,
    load_revenue_anomalies,
    load_lead_enrichments,
)
from pipeline.enrich.factory import get_enricher
from pipeline.report.generate_pdf import generate_report_pdf
from pipeline.notify.slack_webhook import send_slack_notification


def run_pipeline_task(**context):
    logger = logging.getLogger("airflow.task")
    settings = get_settings()
    engine = make_engine()

    wait_for_db(engine)
    # Ensure schema exists (safe to run on every run)
    bootstrap_schema(engine)

    run_id = str(uuid.uuid4())
    started_at = pd.Timestamp.now(tz="UTC")
    
    # 1. Initialize run in DB
    insert_pipeline_run(
        engine, 
        run_id, 
        started_at, 
        settings.enrichment_mode, 
        settings.llm_provider if settings.enrichment_mode == "llm" else None, 
        None # model
    )

    error_msg = None
    status = "failed"
    report_path = None
    slack_sent = False
    rows_extracted = 0
    rows_enriched = 0
    llm_calls = 0
    llm_cost_estimate = 0.0

    try:
        # 2. Extract
        logger.info("Extracting data...")
        source = extract_all(settings)
        rows_extracted = source.total_rows()

        # 3. Load Raw
        logger.info("Loading raw data...")
        load_raw(source, engine)

        # 4. Enrich
        logger.info(f"Enriching data using mode: {settings.enrichment_mode}")
        enricher = get_enricher(settings)

        # 4.1 Tickets
        logger.info("Enriching tickets...")
        tickets_df = enricher.classify_tickets(source.support_tickets)
        load_ticket_classifications(tickets_df, engine, run_id)
        rows_enriched += len(tickets_df)
        
        # 4.2 Reviews
        logger.info("Enriching reviews...")
        reviews_df = enricher.summarize_reviews(source.product_reviews)
        load_review_summaries(reviews_df, engine, run_id)
        rows_enriched += len(reviews_df)
        
        # 4.3 Anomalies
        logger.info("Enriching anomalies...")
        segment_revenue = revenue_segment_frame(source.orders)
        anomalies_df = enricher.detect_anomalies(segment_revenue, threshold=settings.anomaly_threshold)
        load_revenue_anomalies(anomalies_df, engine, run_id)
        rows_enriched += len(anomalies_df)
        
        # 4.4 Leads
        logger.info("Enriching leads...")
        leads_df = enricher.enrich_leads(source.crm_leads)
        load_lead_enrichments(leads_df, engine, run_id)
        rows_enriched += len(leads_df)
        
        llm_calls = enricher.stats.llm_calls
        llm_cost_estimate = enricher.stats.llm_cost_estimate_usd

        # 5. Generate Report
        logger.info("Generating PDF report...")
        report_file = settings.reports_dir / f"run_{run_id}.pdf"
        generate_report_pdf(
            run_id=run_id,
            started_at_str=started_at.isoformat(),
            status="SUCCESS",
            rows_extracted=rows_extracted,
            rows_enriched=rows_enriched,
            output_path=report_file
        )
        report_path = str(report_file)
        
        # 6. Notify
        logger.info("Sending Slack notification...")
        slack_sent = send_slack_notification(f"Pipeline run {run_id} completed successfully. Enriched {rows_enriched} rows.")
        
        status = "success"
    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        error_msg = str(e)
        send_slack_notification(f"Pipeline run {run_id} failed: {error_msg}")
    finally:
        # 7. Finalize
        finished_at = pd.Timestamp.now(tz="UTC")
        finalize_pipeline_run(
            engine=engine,
            run_id=run_id,
            finished_at=finished_at,
            status=status,
            rows_extracted=rows_extracted,
            rows_enriched=rows_enriched,
            llm_calls=llm_calls,
            llm_cost_estimate=llm_cost_estimate,
            report_path=report_path,
            slack_sent=slack_sent,
            error=error_msg,
        )
        if status == "failed":
            raise RuntimeError(f"Pipeline failed: {error_msg}")


default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    "bi_pipeline",
    default_args=default_args,
    description="Automated BI Pipeline with AI Enrichment",
    schedule_interval=timedelta(days=1),
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["bi", "ai", "portfolio"],
) as dag:

    run_pipeline = PythonOperator(
        task_id="run_pipeline",
        python_callable=run_pipeline_task,
    )
