"""LLM-backed enricher — real AI via an OpenAI-compatible endpoint.

Design goals:
    * Provider-agnostic: works with NVIDIA NIM (free), Anthropic Claude
      (paid), Ollama (local) via a single OpenAI-compatible chat API.
    * Structured output: the model is forced to return strict JSON that we
      validate against the expected schema before using it.
    * Safety rails: per-call timeout, bounded retries (tenacity), and
      automatic fallback to the deterministic mock enricher if the LLM is
      unavailable, slow, or returns invalid output. The run is flagged
      ``fell_back_to_mock`` so it's never silently degraded.
    * No secrets in logs: only the provider name and model are logged.

Cost accounting is a coarse estimate (input+output tokens × published rate)
used only for display. It never gates execution.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

import pandas as pd
import requests
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..config import Settings, get_settings
from .base import Enricher
from .mock import (
    MockEnricher,
    _classify_one,
    _detect_language,
    _extractive_summary,
    _infer_size_band,
    _intent_signals,
    _lead_score,
    _top_themes,
    _translate_lead_note,
)

log = logging.getLogger(__name__)

# Rough per-1K-token USD rates for display-only cost estimates.
_RATE_PER_1K = {
    "nvidia": 0.0,            # free tier
    "ollama": 0.0,            # local
    "anthropic": 0.015,       # Claude Sonnet blended in/out (display only)
    "openai-compatible": 0.01,
}


class LLMError(RuntimeError):
    """Raised when the LLM call cannot be completed safely."""


def _estimate_cost(provider: str, n_calls: int, tokens_per_call: int = 1500) -> float:
    rate = _RATE_PER_1K.get(provider, 0.0)
    return round(n_calls * tokens_per_call / 1000 * rate, 6)


class LLMEnricher(Enricher):
    backend_name = "llm"

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__()
        self.settings = settings or get_settings()
        cfg = self.settings.llm_config()  # raises if misconfigured → caught in factory
        self.base_url: str = cfg["base_url"].rstrip("/")
        self.api_key: str = cfg["api_key"]
        self.model: str = cfg["model"]
        self.provider: str = self.settings.llm_provider
        self.timeout: float = self.settings.llm_timeout_seconds
        self.max_retries: int = max(1, self.settings.llm_max_retries)
        self.temperature: float = self.settings.llm_temperature
        self.model_name = self.model
        self.stats.backend = self.provider
        self.stats.model = self.model
        # mock used as a graceful fallback for any sub-call that fails
        self._mock = MockEnricher()

    # ── Low-level call ─────────────────────────────────────────
    def _chat(self, system: str, user: str) -> dict[str, Any]:
        """Call the chat-completions endpoint and return parsed JSON content.

        Retries on network/timeout errors. Raises LLMError on persistent
        failure or non-JSON output so the caller can fall back.
        """
        # Anthropic uses a different request shape; route through a shim.
        if self.provider == "anthropic":
            return self._chat_anthropic(system, user)

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            # Many OpenAI-compatible servers (NVIDIA NIM, Ollama) honour this
            # to force valid JSON.
            "response_format": {"type": "json_object"},
            "max_tokens": 2048,
        }

        @retry(
            stop=stop_after_attempt(self.max_retries + 1),
            wait=wait_exponential(multiplier=1, min=1, max=8),
            retry=retry_if_exception_type((requests.Timeout, requests.ConnectionError)),
            reraise=True,
        )
        def _do() -> dict[str, Any]:
            t0 = time.time()
            resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            log.debug("LLM call ok in %.2fs (provider=%s)", time.time() - t0, self.provider)
            return _safe_json(content)

        try:
            return _do()
        except (RetryError, requests.RequestException, LLMError, KeyError, ValueError) as exc:
            raise LLMError(f"LLM call failed: {exc!r}") from exc

    def _chat_anthropic(self, system: str, user: str) -> dict[str, Any]:
        """Anthropic Messages API shim — returns parsed JSON like the OpenAI path."""
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": self.model,
            "max_tokens": 2048,
            "temperature": self.temperature,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }

        @retry(
            stop=stop_after_attempt(self.max_retries + 1),
            wait=wait_exponential(multiplier=1, min=1, max=8),
            retry=retry_if_exception_type((requests.Timeout, requests.ConnectionError)),
            reraise=True,
        )
        def _do() -> dict[str, Any]:
            resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            content = data["content"][0]["text"]
            return _safe_json(content)

        try:
            return _do()
        except (RetryError, requests.RequestException, LLMError, KeyError, ValueError) as exc:
            raise LLMError(f"Anthropic call failed: {exc!r}") from exc

    # ── Public enrichment API ──────────────────────────────────
    def classify_tickets(self, tickets: pd.DataFrame) -> pd.DataFrame:
        if tickets.empty:
            return self._mock.classify_tickets(tickets)
        # Batch in chunks to keep prompts small and cost predictable.
        try:
            results = self._classify_batch(tickets)
            self.stats.add_cost(len(results) // 5 + 1, _estimate_cost(self.provider, 1))
            self.stats.rows_enriched += len(results)
            return results
        except LLMError as exc:
            log.warning("Ticket classification fell back to mock: %s", exc)
            self.stats.fell_back_to_mock = True
            self.stats.note_error(f"classify_tickets: {exc}")
            return self._mock.classify_tickets(tickets)

    def _classify_batch(self, tickets: pd.DataFrame) -> pd.DataFrame:
        text_col = tickets.get("text") if "text" in tickets.columns else (
            tickets["subject"].fillna("") + ". " + tickets["description"].fillna(""))
        # send at most 40 tickets per call (bounded prompt)
        out_rows: list[dict[str, Any]] = []
        batch_size = 40
        for start in range(0, len(tickets), batch_size):
            chunk = tickets.iloc[start:start + batch_size]
            texts = list(text_col.iloc[start:start + batch_size].astype(str))
            items = [{"id": str(tid), "text": t[:500]}
                     for tid, t in zip(chunk["ticket_id"], texts)]
            system = (
                "You are a multilingual support-ticket classifier. "
                "Return STRICT JSON: {\"results\":[{\"id\":str,\"category\":"
                "oneOf[billing,shipping,bug,feature_request,account,other],"
                "\"sentiment\":oneOf[positive,neutral,negative],"
                "\"urgency\":oneOf[low,medium,high,critical],\"confidence\":0..1}]}. "
                "Detect language from the text; do not translate. No prose."
            )
            user = "Classify each ticket:\n" + json.dumps(items, ensure_ascii=False)
            data = self._chat(system, user)
            for r in data.get("results", []):
                out_rows.append({
                    "ticket_id": r["id"],
                    "category": _coerce(r.get("category"),
                                        ["billing", "shipping", "bug", "feature_request", "account", "other"],
                                        "other"),
                    "sentiment": _coerce(r.get("sentiment"),
                                         ["positive", "neutral", "negative"], "neutral"),
                    "urgency": _coerce(r.get("urgency"),
                                       ["low", "medium", "high", "critical"], "medium"),
                    "confidence": _clamp_float(r.get("confidence"), 0.0, 1.0, 0.7),
                    "detected_language": _detect_language(
                        next((t["text"] for t in items if t["id"] == r["id"]), "")),
                })
        # Fill any ticket the model skipped, deterministically.
        seen = {r["ticket_id"] for r in out_rows}
        for tid, t in zip(tickets["ticket_id"], text_col.astype(str)):
            if tid not in seen:
                cat, sent, urg, conf = _classify_one(t)
                out_rows.append({"ticket_id": tid, "category": cat, "sentiment": sent,
                                 "urgency": urg, "confidence": conf,
                                 "detected_language": _detect_language(t)})
        return pd.DataFrame(out_rows)

    def summarize_reviews(self, reviews: pd.DataFrame) -> pd.DataFrame:
        # Summaries are run per product+month. For the demo we keep the LLM
        # call count small by summarizing the overall corpus shape with the
        # mock and only synthesizing the prose via the LLM.
        base = self._mock.summarize_reviews(reviews)
        if base.empty:
            return base
        try:
            for _, row in base.iterrows():
                sys_prompt = (
                    "You write concise bilingual product-review summaries. "
                    "Return STRICT JSON: {\"summary_en\":str(<=40 words),"
                    "\"summary_fr\":str(<=40 mots)}. No extra keys, no prose."
                )
                user_msg = (
                    f"Product {row['product_id']} ({row['review_window']}): "
                    f"{row['n_reviews']} reviews, avg rating {row['avg_rating']}/5, "
                    f"themes: {row['top_themes']}."
                )
                data = self._chat(sys_prompt, user_msg)
                if "summary_en" in data:
                    base.at[_, "summary_en"] = str(data["summary_en"])[:400]
                if "summary_fr" in data:
                    base.at[_, "summary_fr"] = str(data["summary_fr"])[:400]
                self.stats.add_cost(1, _estimate_cost(self.provider, 1))
            self.stats.rows_enriched += len(base)
            return base
        except LLMError as exc:
            log.warning("Review summarization fell back to mock: %s", exc)
            self.stats.fell_back_to_mock = True
            self.stats.note_error(f"summarize_reviews: {exc}")
            return self._mock.summarize_reviews(reviews)

    def detect_anomalies(self, segment_revenue: pd.DataFrame, *, threshold: float) -> pd.DataFrame:
        # Anomaly detection is statistical and deterministic; no LLM needed.
        # (Using an LLM here would add cost without improving precision.)
        return self._mock.detect_anomalies(segment_revenue, threshold=threshold)

    def enrich_leads(self, leads: pd.DataFrame) -> pd.DataFrame:
        # Lead enrichment combines deterministic scoring (mock) with an LLM
        # translation of the free-text notes — the part where MT adds value.
        base = self._mock.enrich_leads(leads)
        if base.empty:
            return base
        try:
            batch = leads[["lead_id", "notes"]].head(40)
            items = [{"id": str(r.lead_id), "notes": str(r.notes)[:300]}
                     for r in batch.itertuples()]
            sys_prompt = (
                "You are a bilingual FR/EN translator for CRM notes. "
                "Return STRICT JSON: {\"results\":[{\"id\":str,"
                "\"notes_en\":str,\"notes_fr\":str}]}. Translate faithfully; "
                "if already in that language, lightly polish. No prose."
            )
            user_msg = "Translate each lead's notes:\n" + json.dumps(items, ensure_ascii=False)
            data = self._chat(sys_prompt, user_msg)
            by_id = {r["id"]: r for r in data.get("results", [])}
            for idx, lid in enumerate(base["lead_id"]):
                if str(lid) in by_id:
                    r = by_id[str(lid)]
                    if r.get("notes_en"):
                        base.at[idx, "notes_en"] = str(r["notes_en"])[:400]
                    if r.get("notes_fr"):
                        base.at[idx, "notes_fr"] = str(r["notes_fr"])[:400]
            self.stats.add_cost(1, _estimate_cost(self.provider, 1))
            self.stats.rows_enriched += len(base)
            return base
        except LLMError as exc:
            log.warning("Lead translation fell back to mock: %s", exc)
            self.stats.fell_back_to_mock = True
            self.stats.note_error(f"enrich_leads: {exc}")
            return base


# ── helpers ────────────────────────────────────────────────────


def _coerce(val: Any, allowed: list[str], default: str) -> str:
    v = str(val).strip().lower().replace(" ", "_") if val is not None else default
    return v if v in allowed else default


def _clamp_float(val: Any, lo: float, hi: float, default: float) -> float:
    try:
        f = float(val)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, round(f, 3)))


def _safe_json(content: str) -> dict[str, Any]:
    """Parse JSON from an LLM response, tolerating code fences / stray text."""
    if not content:
        raise LLMError("empty LLM response")
    s = content.strip()
    if s.startswith("```"):
        # strip ```json ... ``` fences
        s = s.strip("`")
        s = s.split("\n", 1)[-1] if s.lower().startswith("json") else s
        if s.endswith("```"):
            s = s[:-3]
    # find first {...} and last }
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise LLMError(f"no JSON object in response: {content[:80]!r}")
    blob = s[start:end + 1]
    try:
        return json.loads(blob)
    except json.JSONDecodeError as exc:
        raise LLMError(f"invalid JSON: {exc}") from exc
