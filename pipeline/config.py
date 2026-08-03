"""Centralised, validated configuration for the BI pipeline.

Secrets (API keys, DB passwords) are read ONLY from environment variables
(loaded from a gitignored `.env` via pydantic-settings). They never appear
in source code, logs, the dashboard, or generated reports. Logging at DEBUG
level intentionally masks secret values.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root (this file lives at pipeline/config.py)
ROOT = Path(__file__).resolve().parent.parent

EnrichmentMode = Literal["mock", "llm"]
LLMProvider = Literal["nvidia", "anthropic", "ollama", "openai-compatible"]


class Settings(BaseSettings):
    """Pipeline settings. All fields map 1:1 to env vars (case-insensitive)."""

    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Warehouse DB ───────────────────────────────────────────
    warehouse_db: str = "warehouse"
    warehouse_user: str = "bi_user"
    warehouse_password: SecretStr = SecretStr("bi_dev_password")
    warehouse_host: str = "warehouse"
    warehouse_port: int = 5432
    warehouse_reader_password: SecretStr = SecretStr("reader_dev_password")

    # ── Enrichment mode ────────────────────────────────────────
    enrichment_mode: EnrichmentMode = "mock"
    llm_provider: LLMProvider = "nvidia"

    # ── Provider credentials (all SecretStr — never logged) ───
    nvidia_api_key: SecretStr = SecretStr("")
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_model: str = "deepseek-ai/deepseek-r1"

    anthropic_api_key: SecretStr = SecretStr("")
    anthropic_model: str = "claude-3-5-sonnet-20241022"

    ollama_base_url: str = "http://host.docker.internal:11434/v1"
    ollama_model: str = "llama3.1"

    # ── LLM tuning ─────────────────────────────────────────────
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 2
    llm_temperature: float = 0.0

    # ── Notifications ──────────────────────────────────────────
    slack_webhook_url: SecretStr = SecretStr("")

    # ── Pipeline behaviour ─────────────────────────────────────
    anomaly_threshold: float = 3.0
    run_timezone: str = "Europe/Paris"
    default_lang: Literal["en", "fr"] = "en"

    # ── Convenience paths ──────────────────────────────────────
    @property
    def seed_dir(self) -> Path:
        return ROOT / "data" / "seed"

    @property
    def reports_dir(self) -> Path:
        return ROOT / "reports"

    @property
    def warehouse_dsn(self) -> str:
        """Read/write DSN for the pipeline (postgres)."""
        pw = self.warehouse_password.get_secret_value()
        return (
            f"postgresql+psycopg2://{self.warehouse_user}:{pw}"
            f"@{self.warehouse_host}:{self.warehouse_port}/{self.warehouse_db}"
        )

    @property
    def warehouse_reader_dsn(self) -> str:
        """Read-only DSN used by the dashboard."""
        pw = self.warehouse_reader_password.get_secret_value()
        return (
            f"postgresql+psycopg2://reader:{pw}"
            f"@{self.warehouse_host}:{self.warehouse_port}/{self.warehouse_db}"
        )

    def llm_config(self) -> dict[str, str]:
        """Return the active LLM provider's (base_url, api_key, model).

        Raises ValueError if enrichment_mode != llm. Used by the LLM client.
        """
        if self.enrichment_mode != "llm":
            raise ValueError("llm_config() called but enrichment_mode is not 'llm'")

        if self.llm_provider == "nvidia":
            key = self.nvidia_api_key.get_secret_value()
            if not key:
                raise ValueError("LLM_PROVIDER=nvidia but NVIDIA_API_KEY is not set")
            return {
                "base_url": self.nvidia_base_url,
                "api_key": key,
                "model": self.nvidia_model,
            }
        if self.llm_provider == "anthropic":
            key = self.anthropic_api_key.get_secret_value()
            if not key:
                raise ValueError("LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is not set")
            return {
                "base_url": "https://api.anthropic.com/v1",
                "api_key": key,
                "model": self.anthropic_model,
            }
        if self.llm_provider == "ollama":
            return {
                "base_url": self.ollama_base_url,
                "api_key": "ollama",  # ollama ignores the key but the client needs one
                "model": self.ollama_model,
            }
        # openai-compatible fallback: caller would extend here
        raise ValueError(f"Unsupported LLM_PROVIDER={self.llm_provider!r}")

    @field_validator("anomaly_threshold")
    @classmethod
    def _check_threshold(cls, v: float) -> float:
        if v < 1.0 or v > 10.0:
            raise ValueError("ANOMALY_THRESHOLD must be between 1.0 and 10.0")
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings singleton. Import this, not Settings directly."""
    return Settings()  # type: ignore[call-arg]
