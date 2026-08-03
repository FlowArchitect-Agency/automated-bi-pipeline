"""Automated BI Pipeline with AI Enrichment — core pipeline package.

Modules:
    config    — validated settings loaded from environment / .env
    db        — SQLAlchemy engine helpers for the warehouse
    extract   — pull the 5 demo sources into DataFrames
    transform — clean / type / standardise extracted data
    enrich    — AI enrichment (mock by default, LLM-capable)
    load      — write raw + mart data into the warehouse
    notify    — Slack webhook delivery (graceful skip when unset)
    report    — WeasyPrint PDF report rendering (bilingual)
"""

__version__ = "0.1.0"
