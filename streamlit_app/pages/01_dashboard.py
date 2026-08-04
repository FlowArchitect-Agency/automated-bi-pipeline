import pandas as pd
import plotly.express as px
import streamlit as st

from pipeline.config import get_settings
from pipeline.db import make_engine
from sqlalchemy import text

st.set_page_config(page_title="DataFlow AI | Business Insights", page_icon="📈", layout="wide")

# Inject Premium CSS
try:
    with open("streamlit_app/style.css") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
except FileNotFoundError:
    pass

@st.cache_resource
def get_db_engine():
    settings = get_settings()
    return make_engine(settings.warehouse_reader_dsn)

engine = get_db_engine()

st.markdown('<h1 class="gradient-text">📈 Business Insights Dashboard</h1>', unsafe_allow_html=True)
st.markdown("AI-enriched data from CRM, Support, and E-commerce.")

# Language Toggle for bilingual support
lang = st.radio("Language / Langue", ["English", "Français"], horizontal=True)
is_fr = lang == "Français"

# Fetch Data
@st.cache_data(ttl=300)
def load_data():
    with engine.connect() as conn:
        try:
            tickets = pd.read_sql(text("SELECT * FROM mart.ticket_classifications"), conn)
            anomalies = pd.read_sql(text("SELECT * FROM mart.revenue_anomalies"), conn)
            leads = pd.read_sql(text("SELECT * FROM mart.lead_enrichments"), conn)
            orders = pd.read_sql(text("SELECT * FROM raw.orders"), conn)
            return tickets, anomalies, leads, orders
        except Exception as e:
            st.error(f"Database error: {e}")
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

tickets, anomalies, leads, orders = load_data()

if orders.empty:
    st.warning("No data found. Please run the Airflow pipeline first.")
    st.stop()

# --- TOP KPI METRICS ---
st.markdown("### " + ("Key Performance Indicators" if not is_fr else "Indicateurs de Performance Clés"))
kpi1, kpi2, kpi3, kpi4 = st.columns(4)

with kpi1:
    total_rev = orders['net_revenue_eur'].sum()
    st.metric("Total Revenue" if not is_fr else "Revenu Total", f"€{total_rev:,.0f}")
with kpi2:
    total_orders = len(orders)
    st.metric("Total Orders" if not is_fr else "Commandes Totales", f"{total_orders:,}")
with kpi3:
    total_tickets = len(tickets)
    st.metric("Support Tickets" if not is_fr else "Tickets Support", f"{total_tickets:,}")
with kpi4:
    total_leads = len(leads)
    st.metric("Qualified Leads" if not is_fr else "Leads Qualifiés", f"{total_leads:,}")

st.divider()

# Layout
tab1, tab2, tab3 = st.tabs([
    "E-commerce & Anomalies" if not is_fr else "E-commerce & Anomalies (FR)",
    "Customer Support AI" if not is_fr else "Support Client IA",
    "CRM Lead Scoring" if not is_fr else "Scoring CRM"
])

# Custom Plotly Template Config
PLOTLY_THEME = "plotly_dark"
COLOR_SCALE = ["#00f2fe", "#4facfe", "#f093fb", "#f5576c"]

with tab1:
    st.header("Revenue & Anomaly Detection" if not is_fr else "Revenus et Détection d'Anomalies")

    col1, col2 = st.columns([2, 1])

    with col1:
        # Group orders by date and region
        daily_rev = orders.groupby(['order_date', 'region'])['net_revenue_eur'].sum().reset_index()
        fig_rev = px.line(
            daily_rev, x='order_date', y='net_revenue_eur', color='region',
            title="Daily Net Revenue by Region" if not is_fr else "Revenu Net Quotidien par Région",
            template=PLOTLY_THEME,
            color_discrete_sequence=COLOR_SCALE
        )
        fig_rev.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig_rev, use_container_width=True)

    with col2:
        st.subheader("Detected Anomalies" if not is_fr else "Anomalies Détectées")
        if not anomalies.empty:
            for _, row in anomalies.iterrows():
                icon = "🚨" if row['severity'] == 'critical' else "⚠️"
                st.markdown(f"""
                <div style="background: rgba(255, 87, 108, 0.1); border-left: 4px solid #f5576c; padding: 10px; margin-bottom: 10px; border-radius: 4px;">
                    <strong>{icon} {row['detected_date']}</strong> - {row['dimension']}: {row['dimension_value']}<br/>
                    <small>{row['direction'].title()} in {row['metric']} | Exp: {row['expected_value']} | Act: {row['observed_value']}</small>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("No anomalies detected in recent data." if not is_fr else "Aucune anomalie détectée.")

with tab2:
    st.header("AI Ticket Classification" if not is_fr else "Classification IA des Tickets")
    if not tickets.empty:
        col1, col2 = st.columns(2)
        with col1:
            fig_cat = px.pie(
                tickets, names='category',
                title="Tickets by Category" if not is_fr else "Tickets par Catégorie",
                hole=0.4,
                template=PLOTLY_THEME,
                color_discrete_sequence=COLOR_SCALE
            )
            fig_cat.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig_cat, use_container_width=True)
        with col2:
            fig_sent = px.histogram(
                tickets, x='sentiment', color='urgency', barmode='group',
                title="Sentiment & Urgency" if not is_fr else "Sentiment & Urgence",
                template=PLOTLY_THEME,
                color_discrete_sequence=COLOR_SCALE
            )
            fig_sent.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig_sent, use_container_width=True)
    else:
        st.info("No ticket data available.")

with tab3:
    st.header("Enriched Leads" if not is_fr else "Leads Enrichis")
    if not leads.empty:
        st.dataframe(leads[['lead_id', 'company_size_band', 'lead_score', 'notes_en' if not is_fr else 'notes_fr']], use_container_width=True)
    else:
        st.info("No lead data available.")
