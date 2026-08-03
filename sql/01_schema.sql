-- ═══════════════════════════════════════════════════════════════
-- Automated BI Pipeline with AI Enrichment — warehouse schema
-- Target DB: PostgreSQL 16
-- Two schemas: `raw` (landed source extracts) and `mart` (enriched
-- business views). Pipelines write here; the Streamlit dashboard
-- reads only from `mart` via a restricted `reader` role.
-- ═══════════════════════════════════════════════════════════════

-- ── Roles ──────────────────────────────────────────────────────
-- The compose entrypoint creates `bi_user` (read/write) already.
-- Here we add a read-only `reader` role for the dashboard app.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'reader') THEN
        CREATE ROLE reader LOGIN PASSWORD 'reader_dev_password';
    END IF;
END $$;

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS mart;

GRANT USAGE ON SCHEMA raw, mart TO reader;
GRANT SELECT ON ALL TABLES IN SCHEMA raw, mart TO reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA raw, mart GRANT SELECT ON TABLES TO reader;

-- ═══════════════════════════════════════════════════════════════
-- RAW SCHEMA — landed extracts from the 5 demo data sources
-- ═══════════════════════════════════════════════════════════════

-- 1. E-commerce orders
CREATE TABLE IF NOT EXISTS raw.orders (
    order_id          TEXT PRIMARY KEY,
    customer_id       TEXT NOT NULL,
    order_date        DATE NOT NULL,
    channel           TEXT NOT NULL,           -- web, mobile, marketplace
    region            TEXT NOT NULL,           -- FR, EU, UK, US
    currency          TEXT NOT NULL DEFAULT 'EUR',
    gross_revenue_eur NUMERIC(12,2) NOT NULL,
    discount_eur      NUMERIC(12,2) NOT NULL DEFAULT 0,
    net_revenue_eur   NUMERIC(12,2) NOT NULL,
    units             INTEGER NOT NULL,
    loaded_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 2. Customer support tickets (bilingual FR/EN content)
CREATE TABLE IF NOT EXISTS raw.support_tickets (
    ticket_id     TEXT PRIMARY KEY,
    customer_id   TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL,
    channel       TEXT NOT NULL,               -- email, chat, in_app, phone
    language      TEXT NOT NULL,               -- en, fr
    subject       TEXT NOT NULL,
    description   TEXT NOT NULL,
    status        TEXT NOT NULL,               -- open, pending, solved
    sla_breached  BOOLEAN NOT NULL DEFAULT false,
    loaded_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 3. Product reviews (bilingual FR/EN content)
CREATE TABLE IF NOT EXISTS raw.product_reviews (
    review_id   TEXT PRIMARY KEY,
    product_id  TEXT NOT NULL,
    product_name TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL,
    rating      SMALLINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    language    TEXT NOT NULL,                 -- en, fr
    title       TEXT NOT NULL,
    body        TEXT NOT NULL,
    verified    BOOLEAN NOT NULL DEFAULT false,
    loaded_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 4. Web analytics (daily aggregates)
CREATE TABLE IF NOT EXISTS raw.web_analytics (
    event_date   DATE NOT NULL,
    page_path    TEXT NOT NULL,
    country      TEXT NOT NULL,
    device       TEXT NOT NULL,                -- desktop, mobile, tablet
    sessions     INTEGER NOT NULL,
    pageviews    INTEGER NOT NULL,
    bounce_rate  NUMERIC(5,2) NOT NULL,
    avg_session_sec NUMERIC(10,2) NOT NULL,
    loaded_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (event_date, page_path, country, device)
);

-- 5. CRM leads
CREATE TABLE IF NOT EXISTS raw.crm_leads (
    lead_id        TEXT PRIMARY KEY,
    company_name   TEXT NOT NULL,
    industry       TEXT NOT NULL,
    region         TEXT NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL,
    source         TEXT NOT NULL,              -- organic, referral, ads, event
    status         TEXT NOT NULL,              -- new, contacted, qualified, won, lost
    est_value_eur  NUMERIC(12,2),
    notes          TEXT,
    loaded_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ═══════════════════════════════════════════════════════════════
-- MART SCHEMA — AI-enriched, business-ready views
-- ═══════════════════════════════════════════════════════════════

-- Run-level metadata for every pipeline execution
CREATE TABLE IF NOT EXISTS mart.pipeline_runs (
    run_id              UUID PRIMARY KEY,
    started_at          TIMESTAMPTZ NOT NULL,
    finished_at         TIMESTAMPTZ,
    status              TEXT NOT NULL,                    -- running, success, failed
    enrichment_mode     TEXT NOT NULL,                    -- mock, llm
    llm_provider        TEXT,                             -- nvidia, anthropic, ollama, null
    llm_model           TEXT,
    llm_calls           INTEGER NOT NULL DEFAULT 0,
    llm_cost_estimate   NUMERIC(10,4) NOT NULL DEFAULT 0, -- USD estimate (0 for mock)
    rows_extracted      INTEGER NOT NULL DEFAULT 0,
    rows_enriched       INTEGER NOT NULL DEFAULT 0,
    report_path         TEXT,
    slack_sent          BOOLEAN NOT NULL DEFAULT false,
    error               TEXT
);

-- Enrichment 1: ticket classification
CREATE TABLE IF NOT EXISTS mart.ticket_classifications (
    ticket_id          TEXT PRIMARY KEY REFERENCES raw.support_tickets(ticket_id),
    category           TEXT NOT NULL,           -- billing, shipping, bug, feature_request, account, other
    sentiment          TEXT NOT NULL,           -- positive, neutral, negative
    urgency            TEXT NOT NULL,           -- low, medium, high, critical
    confidence         NUMERIC(4,3) NOT NULL,   -- 0.000 - 1.000
    detected_language  TEXT NOT NULL,
    enriched_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    run_id             UUID REFERENCES mart.pipeline_runs(run_id)
);

-- Enrichment 2: review summarization
CREATE TABLE IF NOT EXISTS mart.review_summaries (
    product_id         TEXT NOT NULL,
    review_window      TEXT NOT NULL,           -- e.g. "2026-07"
    n_reviews          INTEGER NOT NULL,
    avg_rating         NUMERIC(3,2) NOT NULL,
    summary_en         TEXT NOT NULL,
    summary_fr         TEXT NOT NULL,
    top_themes         JSONB NOT NULL,          -- [{"theme": "...", "weight": n}, ...]
    enriched_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    run_id             UUID REFERENCES mart.pipeline_runs(run_id),
    PRIMARY KEY (product_id, review_window)
);

-- Enrichment 3: revenue anomaly detection
CREATE TABLE IF NOT EXISTS mart.revenue_anomalies (
    anomaly_id         TEXT PRIMARY KEY,        -- "date:dimension:value"
    detected_date      DATE NOT NULL,
    dimension          TEXT NOT NULL,           -- channel, region, overall
    dimension_value    TEXT NOT NULL,
    metric             TEXT NOT NULL,           -- net_revenue_eur, units
    observed_value     NUMERIC(14,2) NOT NULL,
    expected_value     NUMERIC(14,2) NOT NULL,
    deviation          NUMERIC(10,3) NOT NULL,  -- standard deviations
    direction          TEXT NOT NULL,           -- spike, drop
    severity           TEXT NOT NULL,           -- warning, critical
    enriched_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    run_id             UUID REFERENCES mart.pipeline_runs(run_id)
);

-- Enrichment 4: lead enrichment (translation + classification)
CREATE TABLE IF NOT EXISTS mart.lead_enrichments (
    lead_id            TEXT PRIMARY KEY REFERENCES raw.crm_leads(lead_id),
    company_size_band  TEXT NOT NULL,           -- 1-10, 11-50, 51-200, 201-1000, 1000+
    lead_score         SMALLINT NOT NULL,       -- 0-100
    intent_signals     JSONB NOT NULL,          -- ["budget mentioned", "timeline: Q3", ...]
    notes_en           TEXT,
    notes_fr           TEXT,
    enriched_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    run_id             UUID REFERENCES mart.pipeline_runs(run_id)
);

-- ── Helpful indexes for dashboard queries ─────────────────────
CREATE INDEX IF NOT EXISTS idx_orders_date   ON raw.orders(order_date);
CREATE INDEX IF NOT EXISTS idx_orders_region ON raw.orders(region);
CREATE INDEX IF NOT EXISTS idx_tickets_created ON raw.support_tickets(created_at);
CREATE INDEX IF NOT EXISTS idx_reviews_created ON raw.product_reviews(created_at);
CREATE INDEX IF NOT EXISTS idx_classif_cat ON mart.ticket_classifications(category);
CREATE INDEX IF NOT EXISTS idx_anom_date ON mart.revenue_anomalies(detected_date);
