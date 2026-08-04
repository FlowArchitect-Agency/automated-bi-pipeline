"""Airflow DAG for the Automated BI Pipeline."""
import logging
import uuid
from datetime import datetime, timedelta

import pandas as pd
from airflow import DAG  # type: ignore[attr-defined]
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


def start_run(**context):
    logger = logging.getLogger("airflow.task")
    settings = get_settings()
    engine = make_engine()

    wait_for_db(engine)
    bootstrap_schema(engine)

    run_id = str(uuid.uuid4())
    started_at = pd.Timestamp.now(tz="UTC").isoformat()
    
    insert_pipeline_run(
        engine, 
        run_id, 
        pd.Timestamp(started_at), 
        settings.enrichment_mode, 
        settings.llm_provider if settings.enrichment_mode == "llm" else None, 
        None
    )
    context["ti"].xcom_push(key="run_id", value=run_id)
    context["ti"].xcom_push(key="started_at", value=started_at)
    logger.info(f"Started pipeline run: {run_id}")


def extract_and_load_raw(**context):
    logger = logging.getLogger("airflow.task")
    settings = get_settings()
    engine = make_engine()

    logger.info("Extracting data...")
    source = extract_all(settings)
    rows_extracted = source.total_rows()

    logger.info("Loading raw data...")
    load_raw(source, engine)
    
    context["ti"].xcom_push(key="rows_extracted", value=rows_extracted)


def enrich_data(**context):
    logger = logging.getLogger("airflow.task")
    settings = get_settings()
    engine = make_engine()
    ti = context["ti"]
    run_id = ti.xcom_pull(task_ids="start_run", key="run_id")

    source = extract_all(settings)

    logger.info(f"Enriching data using mode: {settings.enrichment_mode}")
    enricher = get_enricher(settings)

    rows_enriched = 0
    
    logger.info("Classifying tickets...")
    tickets_df = enricher.classify_tickets(source.support_tickets)
    load_ticket_classifications(tickets_df, engine, run_id)
    rows_enriched += len(tickets_df)
    
    logger.info("Summarizing reviews...")
    reviews_df = enricher.summarize_reviews(source.product_reviews)
    load_review_summaries(reviews_df, engine, run_id)
    rows_enriched += len(reviews_df)
    
    logger.info("Detecting anomalies...")
    segment_revenue = revenue_segment_frame(source.orders)
    anomalies_df = enricher.detect_anomalies(segment_revenue, threshold=settings.anomaly_threshold)
    load_revenue_anomalies(anomalies_df, engine, run_id)
    rows_enriched += len(anomalies_df)
    
    logger.info("Enriching leads...")
    leads_df = enricher.enrich_leads(source.crm_leads)
    load_lead_enrichments(leads_df, engine, run_id)
    rows_enriched += len(leads_df)
    
    ti.xcom_push(key="rows_enriched", value=rows_enriched)
    ti.xcom_push(key="llm_calls", value=enricher.stats.llm_calls)
    ti.xcom_push(key="llm_cost_estimate", value=float(enricher.stats.llm_cost_estimate_usd))


def generate_report(**context):
    settings = get_settings()
    ti = context["ti"]
    
    run_id = ti.xcom_pull(task_ids="start_run", key="run_id")
    started_at_str = ti.xcom_pull(task_ids="start_run", key="started_at")
    rows_extracted = ti.xcom_pull(task_ids="extract_and_load_raw", key="rows_extracted")
    rows_enriched = ti.xcom_pull(task_ids="enrich_data", key="rows_enriched")
    
    report_file = settings.reports_dir / f"run_{run_id}.pdf"
    generate_report_pdf(
        run_id=run_id,
        started_at_str=started_at_str,
        status="SUCCESS",
        rows_extracted=rows_extracted or 0,
        rows_enriched=rows_enriched or 0,
        output_path=report_file
    )
    ti.xcom_push(key="report_path", value=str(report_file))


def finalize_and_notify(**context):
    settings = get_settings()
    engine = make_engine()
    ti = context["ti"]
    
    run_id = ti.xcom_pull(task_ids="start_run", key="run_id")
    rows_extracted = ti.xcom_pull(task_ids="extract_and_load_raw", key="rows_extracted") or 0
    rows_enriched = ti.xcom_pull(task_ids="enrich_data", key="rows_enriched") or 0
    llm_calls = ti.xcom_pull(task_ids="enrich_data", key="llm_calls") or 0
    llm_cost_estimate = ti.xcom_pull(task_ids="enrich_data", key="llm_cost_estimate") or 0.0
    report_path = ti.xcom_pull(task_ids="generate_report", key="report_path")
    
    dag_run = context["dag_run"]
    failed_upstream = any(
        t.state == 'failed' for t in dag_run.get_task_instances() 
        if t.task_id != 'finalize_and_notify'
    )
    status = "failed" if failed_upstream else "success"
    
    slack_sent = False
    if status == "success":
        slack_sent = send_slack_notification(f"Pipeline run {run_id} completed successfully. Enriched {rows_enriched} rows.")
    else:
        send_slack_notification(f"Pipeline run {run_id} failed. Please check Airflow logs.")
        
    finalize_pipeline_run(
        engine=engine,
        run_id=run_id,
        finished_at=pd.Timestamp.now(tz="UTC"),
        status=status,
        rows_extracted=rows_extracted,
        rows_enriched=rows_enriched,
        llm_calls=llm_calls,
        llm_cost_estimate=llm_cost_estimate,
        report_path=report_path,
        slack_sent=slack_sent,
        error="Upstream task failed" if failed_upstream else None,
    )
    if status == "failed":
        raise RuntimeError("Pipeline failed due to upstream errors.")

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

    t_start = PythonOperator(task_id="start_run", python_callable=start_run)
    t_extract = PythonOperator(task_id="extract_and_load_raw", python_callable=extract_and_load_raw)
    t_enrich = PythonOperator(task_id="enrich_data", python_callable=enrich_data)
    t_report = PythonOperator(task_id="generate_report", python_callable=generate_report)
    t_finalize = PythonOperator(task_id="finalize_and_notify", python_callable=finalize_and_notify, trigger_rule="all_done")

    t_start >> t_extract >> t_enrich >> t_report >> t_finalize
