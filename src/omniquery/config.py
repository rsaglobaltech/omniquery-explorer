from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LlmProvider = Literal["ollama", "openai", "anthropic"]
Environment = Literal["development", "staging", "production"]


class LlmSettings(BaseSettings):
    """LLM provider configuration."""

    model_config = SettingsConfigDict(env_prefix="LLM_", extra="ignore")

    provider: LlmProvider = "ollama"
    model: str = "llama3.2:latest"
    embedding_model: str = "nomic-embed-text"
    timeout: float = 300.0
    max_retries: int = 3

    # Provider-specific
    ollama_base_url: str = "http://localhost:11434"
    openai_api_key: SecretStr | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    anthropic_api_key: SecretStr | None = None
    anthropic_base_url: str = "https://api.anthropic.com"


class DatabaseSettings(BaseSettings):
    """Target database default connection."""

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    database_url: SecretStr | None = Field(default=None, alias="DATABASE_URL")
    statement_timeout_ms: int = Field(default=30_000, alias="DB_STATEMENT_TIMEOUT_MS")
    max_rows_default: int = Field(default=500, alias="DB_MAX_ROWS_DEFAULT")


class CacheSettings(BaseSettings):
    """Local cache configuration."""

    model_config = SettingsConfigDict(env_prefix="CACHE_", extra="ignore")

    enabled: bool = True
    dir: Path = Path(".tmp/cache")
    schema_ttl_seconds: int = 3600
    profile_ttl_seconds: int = 1800
    embedding_ttl_seconds: int = 86_400

    @field_validator("dir")
    @classmethod
    def _resolve_dir(cls, v: Path) -> Path:
        v.mkdir(parents=True, exist_ok=True)
        return v.resolve()


class PersistenceSettings(BaseSettings):
    """Internal persistence (sessions, query log) configuration."""

    model_config = SettingsConfigDict(env_prefix="PERSIST_", extra="ignore")

    enabled: bool = True
    database_url: str = "sqlite+aiosqlite:///.tmp/omniquery.db"


class WebSettings(BaseSettings):
    """HTTP adapter configuration (P0.3 rate-limit, CORS, etc.)."""

    model_config = SettingsConfigDict(env_prefix="WEB_", extra="ignore")

    # Requests per minute per identity (API key, or client IP when
    # unauthenticated routes are enabled). 0 disables the limiter.
    rate_limit_per_minute: int = 60
    # Comma-separated CORS origins; empty string keeps the FastAPI default
    # (no extra origins beyond '*' which the app currently applies).
    cors_origins: str = "*"


class CostGuardSettings(BaseSettings):
    """Cost-guard thresholds (P1.10).

    Used by the SQL execution path to reject queries whose estimated cost
    or row scan is unreasonable, and to cap per-session usage.
    """

    model_config = SettingsConfigDict(env_prefix="COST_", extra="ignore")

    # Enable EXPLAIN-based plan inspection before executing the query.
    # Disabled by default since some users may not grant EXPLAIN privileges.
    explain_enabled: bool = False
    # Reject when the planner estimates higher cost than this (Postgres cost units).
    max_plan_cost: float = 1_000_000.0
    # Reject when the planner estimates scanning more than this many rows.
    max_plan_rows: int = 50_000_000
    # Per-session caps tracked in-process; reset on container restart.
    max_queries_per_session: int = 100
    max_tokens_per_session: int = 1_000_000


class PiiSettings(BaseSettings):
    """PII masking policy (P1.11).

    Columns matched by ``denylist_patterns`` (case-insensitive regex) are:
    - excluded from the schema DDL fed to the LLM, and
    - masked in any rows returned to the caller.
    """

    model_config = SettingsConfigDict(env_prefix="PII_", extra="ignore")

    enabled: bool = True
    # Comma-separated regex list (parsed in PiiPolicy). Default covers
    # the most common sensitive identifiers.
    denylist_patterns: str = (
        r"^(email|email_address|e_mail|password|passwd|pwd|"
        r"ssn|social_security|tax_id|nif|cpf|"
        r"credit_card|card_number|cvv|cvc|iban|bic|swift|"
        r"phone|phone_number|telephone|mobile|"
        r"address|street|postal_code|zip_code|"
        r"birth_date|date_of_birth|dob|"
        r"api_key|secret|token|access_token|refresh_token)$"
    )
    # Replacement token shown instead of the real value.
    mask_value: str = "***"


class ObservabilitySettings(BaseSettings):
    """Logging and tracing configuration."""

    model_config = SettingsConfigDict(env_prefix="OBS_", extra="ignore")

    log_level: str = "INFO"
    log_payload_limit: int = 2000
    otel_enabled: bool = False
    otel_endpoint: str | None = None


class Settings(BaseSettings):
    """Root application settings — composes nested configs."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Environment = "development"
    llm: LlmSettings = Field(default_factory=LlmSettings)
    db: DatabaseSettings = Field(default_factory=DatabaseSettings)
    cache: CacheSettings = Field(default_factory=CacheSettings)
    persistence: PersistenceSettings = Field(default_factory=PersistenceSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    cost: CostGuardSettings = Field(default_factory=CostGuardSettings)
    pii: PiiSettings = Field(default_factory=PiiSettings)
    web: WebSettings = Field(default_factory=WebSettings)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide singleton Settings."""
    return Settings()
