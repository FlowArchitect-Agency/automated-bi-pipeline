"""Deterministic mock enricher — zero-cost, offline, always available.

This is NOT a placeholder that returns random noise. It implements the four
enrichment operations with real (if simple) logic:
    - classify_tickets  : keyword rules → category/sentiment/urgency
    - summarize_reviews : extractive summarization + theme frequency
    - detect_anomalies  : z-score over the segment's own history
    - enrich_leads      : rule-based scoring + label translation

Results are deterministic given the same input, so tests are reproducible.
It is honestly labeled "mock enrichment" in the dashboard and PDF.
"""
from __future__ import annotations

import re
from collections import Counter

import numpy as np
import pandas as pd

from .base import Enricher


def _text_series(df: pd.DataFrame) -> pd.Series:
    """Return the combined text column for a frame, deriving it if absent.

    Prefers an existing ``text`` column; otherwise concatenates subject+description
    or title+body. Always returns a real Series (never the column *name* string).
    """
    if "text" in df.columns:
        return df["text"].fillna("").astype(str)
    if {"subject", "description"}.issubset(df.columns):
        return (df["subject"].fillna("") + ". " + df["description"].fillna("")).astype(str)
    if {"title", "body"}.issubset(df.columns):
        return (df["title"].fillna("") + ". " + df["body"].fillna("")).astype(str)
    return pd.Series([""] * len(df), index=df.index)

# ── Ticket classification rules ────────────────────────────────
_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "billing": ["invoice", "charged", "refund", "payment", "subscription", "renewal",
                "factur", "remboursement", "abonnement", "paiement"],
    "shipping": ["shipping", "delivery", "package", "tracking", "arrived", "damaged",
                 "livraison", "colis", "retard", "suivi"],
    "bug": ["bug", "crash", "error", "broken", "500", "doesn't work", "doesn't load",
            "plante", "bug", "erreur", "cassé", "ne charge", "500"],
    "feature_request": ["add", "feature", "request", "would love", "please add", "roadmap",
                        "ajouter", "demande", "ce serait super", "mode sombre"],
    "account": ["password", "login", "two-factor", "2fa", "account", "reset",
                "mot de passe", "compte", "connexion", "2fa"],
}

# Urgency heuristics
_URGENCY_HIGH = ["urgent", "asap", "critical", "down", "cannot", "broken", "blocked",
                 "frustrated", "angry", "urgent"]
_URGENCY_CRITICAL = ["outage", "data loss", "security", "breach", "legal"]

_NEGATIVE = ["frustrated", "angry", "disappointed", "broken", "crash", "error", "worst",
             "terrible", "can't", "cannot", "fails", "déçu", "frustré", "furieux",
             "cassé", "plante", "erreur", "pire"]
_POSITIVE = ["love", "great", "excellent", "happy", "thank", "best", "amazing",
             "adore", "super", "génial", "merci", "parfait"]


def _detect_language(text: str) -> str:
    """Trivial heuristic: French if it contains accented chars or common FR words."""
    fr_markers = {"le", "la", "les", "je", "nous", "vous", "avec", "pour", "une", "des",
                  "mais", "s'il", "merci", "facture", "colis", "erreur"}
    tokens = re.findall(r"[a-zA-Zàâäéèêëîïôöùûüç]+", text.lower())
    if not tokens:
        return "en"
    # accent presence is a strong FR signal
    if re.search(r"[àâäéèêëîïôöùûüç]", text.lower()):
        return "fr"
    fr_hits = sum(1 for t in tokens if t in fr_markers)
    return "fr" if fr_hits >= 2 else "en"


def _classify_one(text: str) -> tuple[str, str, str, float]:
    """Return (category, sentiment, urgency, confidence)."""
    t = text.lower()

    # category: pick the keyword set with the most hits
    best_cat, best_hits = "other", 0
    for cat, kws in _CATEGORY_KEYWORDS.items():
        hits = sum(1 for kw in kws if kw in t)
        if hits > best_hits:
            best_cat, best_hits = cat, hits

    # sentiment
    neg = sum(1 for w in _NEGATIVE if w in t)
    pos = sum(1 for w in _POSITIVE if w in t)
    if neg > pos:
        sentiment = "negative"
    elif pos > neg:
        sentiment = "positive"
    else:
        sentiment = "neutral"

    # urgency
    if any(w in t for w in _URGENCY_CRITICAL):
        urgency = "critical"
    elif any(w in t for w in _URGENCY_HIGH):
        urgency = "high"
    elif sentiment == "negative":
        urgency = "medium"
    else:
        urgency = "low"

    # confidence: scaled by keyword hits, capped
    confidence = min(0.95, 0.45 + 0.12 * best_hits + (0.05 if sentiment != "neutral" else 0))
    return best_cat, sentiment, urgency, round(confidence, 3)


# ── Review summarization (extractive) ──────────────────────────
_THEME_KEYWORDS: dict[str, list[str]] = {
    "ui_ux": ["ui", "interface", "design", "intuitive", "dashboard", "layout"],
    "performance": ["slow", "slowdown", "fast", "performance", "lag", "speed", "ralentissement"],
    "bugs": ["bug", "crash", "error", "broken", "doesn't work", "plante", "erreur"],
    "pricing": ["price", "pricing", "expensive", "cost", "value", "roi", "prix", "cher"],
    "support": ["support", "help", "response", "team", "service"],
    "onboarding": ["onboarding", "setup", "migrate", "migration", "intégration"],
    "integrations": ["integration", "api", "sso", "connect", "workflow"],
    "features": ["feature", "automation", "export", "csv", "dark mode", "fonctionnalité"],
}


def _top_themes(texts: pd.Series, top_n: int = 5) -> list[dict[str, object]]:
    counts: Counter[str] = Counter()
    for t in texts.str.lower():
        for theme, kws in _THEME_KEYWORDS.items():
            if any(kw in t for kw in kws):
                counts[theme] += 1
    max(1, len(texts))
    return [{"theme": th, "weight": int(n)} for th, n in counts.most_common(top_n)]


def _extractive_summary(texts: pd.Series, lang: str, max_sentences: int = 2) -> str:
    """Naive extractive summary: most frequent 'representative' sentences.

    Picks the first sentence of the most common review bodies. Good enough to
    be informative; an LLM would do this far better (that's the point of the
    dual-mode design).
    """
    if texts.empty:
        return ""
    # take whole-body strings, pick the most representative by rating proximity
    bodies = texts.dropna().astype(str).tolist()
    if not bodies:
        return ""
    # frequency of each body
    freq = Counter(bodies)
    top = [b for b, _ in freq.most_common(max_sentences)]
    return " ".join(top)


# ── Anomaly detection (z-score) ────────────────────────────────
def _zscore_anomalies(group: pd.DataFrame, metric: str, threshold: float) -> pd.DataFrame:
    """Flag rows whose |z-score| of `metric` exceeds threshold within the group."""
    s = group[metric].astype(float)
    mu = s.mean()
    sigma = s.std(ddof=0)
    if sigma == 0 or np.isnan(sigma):
        return pd.DataFrame(columns=["order_date", metric, "z", "expected", "direction"])
    z = (s - mu) / sigma
    mask = z.abs() >= threshold
    out = group.loc[mask, ["order_date", metric]].copy()
    out["z"] = z[mask]
    out["expected"] = mu
    out["direction"] = np.where(out["z"] > 0, "spike", "drop")
    return out


# ── Lead enrichment ────────────────────────────────────────────
_SIZE_BANDS = [(1, 10), (11, 50), (51, 200), (201, 1000), (1001, 10**9)]


def _infer_size_band(notes: str) -> str:
    m = re.search(r"~?\s*(\d{1,4})\s*(?:people|personnes|p)?", notes.lower())
    if not m:
        return "11-50"  # default mid-band
    n = int(m.group(1))
    for lo, hi in _SIZE_BANDS:
        if lo <= n <= hi:
            return f"{lo}-{hi if hi < 10**6 else '1000+'}"
    return "11-50"


def _lead_score(row: pd.Series) -> int:
    """Heuristic 0-100 score from status, source, value, notes signals."""
    notes = str(row.get("notes", "")).lower()
    score = 30
    score += {"new": 5, "contacted": 15, "qualified": 35, "won": 50, "lost": -20}.get(
        str(row.get("status")), 0)
    score += {"referral": 12, "event": 8, "organic": 5, "ads": 2}.get(
        str(row.get("source")), 0)
    val = row.get("est_value_eur")
    if pd.notna(val):
        score += min(20, int(float(val) / 5000))
    if any(w in notes for w in ["budget", "confirmed", "q3", "t3", "demo", "sso", "api", "annual"]):
        score += 15
    if "objection" in notes or "price" in notes or "prix" in notes or "cher" in notes:
        score -= 10
    return max(0, min(100, score))


def _intent_signals(notes: str) -> list[str]:
    t = notes.lower()
    signals: list[str] = []
    if any(w in t for w in ["budget", "budget confirmé"]):
        signals.append("budget_confirmed")
    if re.search(r"\bq[1-4]\b|t[1-4]|next quarter|fin de trimestre", t):
        signals.append("timeline_indicated")
    if any(w in t for w in ["demo", "démo"]):
        signals.append("requested_demo")
    if any(w in t for w in ["sso", "api", "annual", "annuel"]):
        signals.append("product_fit_signals")
    if any(w in t for w in ["alternative", "evaluating", "évalue", "migrate", "migration"]):
        signals.append("evaluating_alternatives")
    if any(w in t for w in ["objection", "price", "prix", "cher", "smaller team", "plus petite"]):
        signals.append("pricing_objection")
    return signals or ["no_clear_signal"]


# Tiny honest FR↔EN glossary for the lead-notes translation in mock mode.
_GLOSSARY_EN_FR = {
    "Budget confirmed for Q3": "Budget confirmé pour T3",
    "Evaluating alternatives to": "Évalue des alternatives à",
    "Interested in annual plan": "Intéressé par le plan annuel",
    "Needs SSO and the API": "Besoin du SSO et de l'API",
    "Decision by end of quarter": "Décision d'ici la fin du trimestre",
    "Referred by existing customer": "Recommandé par un client existant",
    "Pricing objection": "Objection sur le prix",
    "Nurture for next cycle": "À cultiver pour le prochain cycle",
    "Large team": "Grande équipe",
    "Smaller team than expected": "Équipe plus petite que prévu",
    "Inbound from": "Entrant via",
    "Met at": "Rencontré via",
    "people": "personnes",
    "Spoke with": "Échangé avec le/la",
    "Currently using": "Utilise actuellement",
    "Wants demo next week": "Démo la semaine prochaine",
}
_GLOSSARY_FR_EN = {v: k for k, v in _GLOSSARY_EN_FR.items()}


def _translate_lead_note(notes: str, target_lang: str) -> str:
    """Word-replacement 'translation' — explicitly a mock, not real MT."""
    gloss = _GLOSSARY_EN_FR if target_lang == "fr" else _GLOSSARY_FR_EN
    out = notes
    # longest-first to avoid partial overlaps
    for src in sorted(gloss, key=len, reverse=True):
        out = out.replace(src, gloss[src])
    return out


class MockEnricher(Enricher):
    backend_name = "mock"
    model_name = "rule-based (deterministic)"

    def classify_tickets(self, tickets: pd.DataFrame) -> pd.DataFrame:
        if tickets.empty:
            return tickets.assign(category=[], sentiment=[], urgency=[],
                                  confidence=[], detected_language=[])
        text_col = _text_series(tickets)
        rows = []
        for tid, t in zip(tickets["ticket_id"], text_col, strict=False):
            cat, sent, urg, conf = _classify_one(str(t))
            rows.append((tid, cat, sent, urg, conf, _detect_language(str(t))))
        out = pd.DataFrame(rows, columns=[
            "ticket_id", "category", "sentiment", "urgency", "confidence", "detected_language"])
        self.stats.rows_enriched += len(out)
        return out

    def summarize_reviews(self, reviews: pd.DataFrame) -> pd.DataFrame:
        if reviews.empty:
            return pd.DataFrame(columns=[
                "product_id", "review_window", "n_reviews", "avg_rating",
                "summary_en", "summary_fr", "top_themes"])
        df = reviews.copy()
        df["created_at"] = pd.to_datetime(df["created_at"])
        df["review_window"] = df["created_at"].dt.to_period("M").astype(str)

        # Derive a per-row text column used for summarization (title + body when
        # a real text column is absent). This mirrors the rest of the module.
        if "text" not in df.columns:
            if {"title", "body"}.issubset(df.columns):
                df["text"] = df["title"].fillna("") + " " + df["body"].fillna("")
            elif "body" in df.columns:
                df["text"] = df["body"].fillna("")
            else:
                df["text"] = ""

        # NOTE: We intentionally avoid ``df.groupby(keys).apply(...)`` operating on
        # the grouping columns. On Pandas >= 2.2 that emits a FutureWarning and on
        # Pandas 1.5.3 the ``include_groups=`` argument used to silence it does not
        # exist. Iterating the groups and building rows by hand is fully
        # deterministic and works identically across the supported range
        # (1.5.3 .. 2.x) with no deprecation warnings.
        rows: list[dict[str, object]] = []
        for (product_id, window), g in df.groupby(["product_id", "review_window"], sort=False):
            lang = g["language"] if "language" in g.columns else None
            bodies = g["body"].astype(str) if "body" in g.columns else pd.Series(dtype=str)
            if lang is not None:
                en_bodies = bodies[lang.values == "en"]
                fr_bodies = bodies[lang.values == "fr"]
            else:
                en_bodies = fr_bodies = bodies
            rows.append({
                "product_id": product_id,
                "review_window": window,
                "n_reviews": len(g),
                "avg_rating": round(float(g["rating"].astype(float).mean()), 2),
                "summary_en": _extractive_summary(en_bodies, "en") or _extractive_summary(bodies, "en"),
                "summary_fr": _extractive_summary(fr_bodies, "fr") or _extractive_summary(bodies, "fr"),
                "top_themes": _top_themes(g["text"].astype(str)),
            })

        out = pd.DataFrame(rows, columns=[
            "product_id", "review_window", "n_reviews", "avg_rating",
            "summary_en", "summary_fr", "top_themes"])
        out["top_themes"] = out["top_themes"].apply(lambda x: x if isinstance(x, list) else [])
        self.stats.rows_enriched += len(out)
        return out

    def detect_anomalies(self, segment_revenue: pd.DataFrame, *, threshold: float) -> pd.DataFrame:
        if segment_revenue.empty:
            return pd.DataFrame(columns=[
                "anomaly_id", "detected_date", "dimension", "dimension_value",
                "metric", "observed_value", "expected_value", "deviation",
                "direction", "severity"])

        rows = []
        # analyse per (channel, region) segment AND the overall rollup
        for (ch, reg), g in segment_revenue.groupby(["channel", "region"], observed=True):
            dim = "overall" if (ch == "all" and reg == "all") else (
                "channel" if reg == "all" else ("region" if ch == "all" else "channel_region"))
            dim_val = f"{ch}/{reg}" if dim == "channel_region" else (ch if dim == "channel" else reg)
            for metric in ["net_revenue_eur", "units"]:
                an = _zscore_anomalies(g.sort_values("order_date"), metric, threshold)
                for _, r in an.iterrows():
                    dev = float(r["z"])
                    severity = "critical" if abs(dev) >= threshold + 2 else "warning"
                    obs = float(r[metric])
                    rows.append({
                        "anomaly_id": f"{r['order_date']}:{dim}:{dim_val}:{metric}",
                        "detected_date": pd.to_datetime(r["order_date"]).date(),
                        "dimension": dim,
                        "dimension_value": dim_val,
                        "metric": metric,
                        "observed_value": round(obs, 2),
                        "expected_value": round(float(r["expected"]), 2),
                        "deviation": round(dev, 3),
                        "direction": r["direction"],
                        "severity": severity,
                    })
        out = pd.DataFrame(rows)
        self.stats.rows_enriched += len(out)
        return out

    def enrich_leads(self, leads: pd.DataFrame) -> pd.DataFrame:
        if leads.empty:
            return leads.assign(company_size_band=[], lead_score=[], intent_signals=[],
                                notes_en=[], notes_fr=[])
        out = pd.DataFrame({
            "lead_id": leads["lead_id"],
            "company_size_band": leads["notes"].astype(str).apply(_infer_size_band),
            "lead_score": leads.apply(_lead_score, axis=1).astype(int),
            "intent_signals": leads["notes"].astype(str).apply(lambda n: _intent_signals(n)),
            "notes_en": leads["notes"].astype(str).apply(lambda n: _translate_lead_note(n, "en")),
            "notes_fr": leads["notes"].astype(str).apply(lambda n: _translate_lead_note(n, "fr")),
        })
        self.stats.rows_enriched += len(out)
        return out
