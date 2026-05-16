"""Pydantic request/response models for the Web API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, SecretStr


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    connection_url: SecretStr
    max_rows: int = Field(default=500, ge=1, le=10_000)


class ExploreRequest(BaseModel):
    connection_url: SecretStr
    max_rows: int = Field(default=500, ge=1, le=10_000)


class SchemaRequest(BaseModel):
    connection_url: SecretStr


class AskResponse(BaseModel):
    question: str
    generated_sql: str
    row_count: int
    rows: list[dict[str, Any]]
    report: str
    error: str = ""


class HealthResponse(BaseModel):
    status: str = "ok"
    environment: str
    llm_provider: str
    llm_model: str
