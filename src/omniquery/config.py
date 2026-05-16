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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide singleton Settings."""
    return Settings()
