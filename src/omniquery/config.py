from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LlmProvider = Literal["ollama", "openai", "anthropic", "bedrock", "vertex"]
Environment = Literal["development", "staging", "production"]
# Languages supported by the localised prompt registry. ``auto`` means
# the resolver inspects the question text on every call and picks the
# best match.
Language = Literal["en", "es", "auto"]


class LlmSettings(BaseSettings):
    """LLM provider configuration."""

    model_config = SettingsConfigDict(env_prefix="LLM_", extra="ignore")

    provider: LlmProvider = "ollama"
    model: str = "llama3.2:latest"
    embedding_model: str = "nomic-embed-text"
    timeout: float = 300.0
    max_retries: int = 3
    # Output language for proposed questions, DB summaries, and EDA
    # reports. ``auto`` detects per call from the user's question.
    # Generated SQL itself is always plain SQL — only the natural-
    # language wrappers around it follow this setting.
    language: Language = "auto"

    # Provider-specific
    ollama_base_url: str = "http://localhost:11434"
    openai_api_key: SecretStr | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    anthropic_api_key: SecretStr | None = None
    anthropic_base_url: str = "https://api.anthropic.com"
    # AWS Bedrock — credentials resolved by boto3 (env vars, ~/.aws,
    # instance role, ...). We only need the region; ``LLM_MODEL`` holds
    # the Bedrock model id (e.g. anthropic.claude-3-5-sonnet-20241022-v2:0).
    bedrock_region: str = "us-east-1"
    # Google Vertex AI — same pattern: ADC handles auth, settings hold
    # the project/region/publisher knobs.
    vertex_project: str | None = None
    vertex_region: str = "us-east5"


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


class SemanticCacheSettings(BaseSettings):
    """Semantic cache of (question → generated_sql) pairs (P2.15).

    Each successful run is embedded and stored. On the next question
    we look up the closest past entry by cosine similarity and, if it
    crosses ``threshold``, reuse its SQL — skipping the LLM altogether.

    Disabled by default because reuse must be opt-in: the SQL may be
    out of date if the schema changed since it was first produced.
    """

    model_config = SettingsConfigDict(env_prefix="SEMANTIC_CACHE_", extra="ignore")

    enabled: bool = False
    # Minimum cosine similarity to count as a hit. 0.92 keeps recall
    # high while rejecting paraphrases that change analytical intent
    # (e.g. "top customers" vs "least active customers").
    threshold: float = 0.92
    # Cap on stored entries; oldest entries are evicted first. Cosine
    # search is linear so this also caps lookup latency.
    max_entries: int = 500
    # Bucket name under CACHE_DIR (the parent CacheSettings owns the root).
    namespace: str = "semantic_queries"


class MemorySettings(BaseSettings):
    """Conversational memory (LangGraph checkpoints) configuration.

    When enabled, the LangGraph state machine receives a checkpointer
    so a session can resume on the same ``thread_id`` and the agent
    sees prior turns. Backends:

    - ``memory``: in-process only, lost on restart (good for tests and
      single-shot CLI).
    - ``sqlite``: file-backed; requires the optional
      ``langgraph-checkpoint-sqlite`` package.
    """

    model_config = SettingsConfigDict(env_prefix="MEMORY_", extra="ignore")

    enabled: bool = False
    backend: Literal["memory", "sqlite"] = "memory"
    sqlite_path: Path = Path(".tmp/memory.sqlite")


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
    memory: MemorySettings = Field(default_factory=MemorySettings)
    semantic_cache: SemanticCacheSettings = Field(default_factory=SemanticCacheSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    cost: CostGuardSettings = Field(default_factory=CostGuardSettings)
    pii: PiiSettings = Field(default_factory=PiiSettings)
    web: WebSettings = Field(default_factory=WebSettings)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide singleton Settings."""
    return Settings()
