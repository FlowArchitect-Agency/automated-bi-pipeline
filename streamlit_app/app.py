import streamlit as st
import pandas as pd
from sqlalchemy import text
from pipeline.config import get_settings
from pipeline.db import make_engine

st.set_page_config(
    page_title="DataFlow AI | Home",
    page_icon="🌊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("DataFlow AI: Automated BI & Enrichment Pipeline")
st.markdown("### Welcome to the Control Center")
st.markdown("""
This platform orchestrates your daily business data, extracting from core systems (CRM, e-commerce, customer support), enriching it with AI, and serving actionable intelligence.

**What this pipeline does:**
- 📥 **Extracts** from 5 disparate sources.
- 🧠 **Enriches** unstructured data (ticket classification, review summarization) and detects anomalies.
- 💾 **Stores** enriched views in a structured PostgreSQL data mart.
- 📊 **Delivers** insights right here and via scheduled Slack & PDF reports.
""")

@st.cache_resource
def get_db_engine():
    settings = get_settings()
    # Streamlit uses the reader connection for security
    return make_engine(settings.warehouse_reader_dsn)

def fetch_recent_runs(engine, limit=5):
    try:
        with engine.connect() as conn:
            query = text('''
                SELECT run_id, started_at, finished_at, status, enrichment_mode, 
                       rows_extracted, rows_enriched, report_path, error 
                FROM mart.pipeline_runs 
                ORDER BY started_at DESC LIMIT :limit
            ''')
            return pd.read_sql(query, conn, params={"limit": limit})
    except Exception as e:
        st.error(f"Failed to connect to database: {e}")
        return pd.DataFrame()

engine = get_db_engine()

st.divider()
st.subheader("Recent Pipeline Executions")

runs_df = fetch_recent_runs(engine)
if not runs_df.empty:
    for _, row in runs_df.iterrows():
        status_color = "🟢" if row['status'] == "success" else "🔴" if row['status'] == "failed" else "🟡"
        
        with st.expander(f"{status_color} Run: {row['started_at'].strftime('%Y-%m-%d %H:%M:%S UTC')} ({row['status'].upper()})"):
            col1, col2, col3 = st.columns(3)
            col1.metric("Rows Extracted", row['rows_extracted'])
            col2.metric("Rows Enriched", row['rows_enriched'])
            col3.metric("Enrichment Mode", row['enrichment_mode'].upper())
            
            st.markdown(f"**Run ID:** `{row['run_id']}`")
            if row['status'] == "success":
                st.success("Pipeline executed successfully. PDF report generated.")
                if row['report_path']:
                    st.info(f"Report saved at: `{row['report_path']}`")
            elif row['status'] == "failed":
                st.error(f"Pipeline failed: {row['error']}")
else:
    st.info("No pipeline runs found. Trigger the DAG in Airflow to see results here.")

st.sidebar.success("Select a dashboard page above to view business insights.")
