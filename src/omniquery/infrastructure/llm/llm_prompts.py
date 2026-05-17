"""Prompt builders shared by all chat-style LLM adapters.

Templates live in ``omniquery.infrastructure.llm.i18n`` keyed by locale
(en/es). Each builder picks the locale through ``resolve_locale`` so
adapters stay completely unaware of language plumbing.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from omniquery.config import get_settings
from omniquery.domain.entities.database_schema import DatabaseSchema
from omniquery.domain.entities.eda_query import EdaQuery
from omniquery.infrastructure.llm.i18n import (
    FIX_SQL,
    GENERATE_SQL,
    PROPOSE_QUESTIONS,
    REPORT,
    SUMMARIZE_DB,
    TABLE_SELECTION,
    Locale,
    resolve_locale,
)

_SYSTEM_PROMPT_PATH = Path(__file__).parents[4] / "docs" / "system_prompt.md"

_NON_SELECT = re.compile(
    r"^\s*(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE)\b",
    re.IGNORECASE,
)

_TABLE_REF = re.compile(
    r"\b(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_]*)(?:\s+(?:AS\s+)?[a-zA-Z_][a-zA-Z0-9_]*)?",
    re.IGNORECASE,
)


def load_system_prompt() -> str:
    if _SYSTEM_PROMPT_PATH.exists():
        return _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    return ""


def extract_table_names(sql: str) -> list[str]:
    return list(dict.fromkeys(m.group(1) for m in _TABLE_REF.finditer(sql)))


def extract_sql(text: str) -> str:
    cleaned = re.sub(r"```(?:sql)?\s*(.*?)```", r"\1", text, flags=re.DOTALL)
    return cleaned.strip()


def assert_select_only(sql: str) -> None:
    if _NON_SELECT.match(sql):
        raise ValueError(f"LLM returned a non-SELECT statement: {sql[:120]!r}")


def _locale_for(query: EdaQuery) -> Locale:
    """Resolve the locale for this call.

    Priority:
    1. ``query.language`` if the entity carries one (planned future field).
    2. ``LLM_LANGUAGE`` setting + question text via the i18n resolver.
    """
    setting = get_settings().llm.language
    return resolve_locale(setting, query.question or "")


def build_table_selection_prompt(schema: DatabaseSchema, query: EdaQuery) -> str:
    all_table_names = "\n".join(f"- {n}" for n in schema.table_names)
    return TABLE_SELECTION[_locale_for(query)].format(
        engine=schema.engine.value,
        db_name=schema.db_name,
        tables=all_table_names,
        question=query.question,
    )


def build_generate_sql_prompt(
    schema: DatabaseSchema, query: EdaQuery, verified_ddl: str
) -> str:
    return GENERATE_SQL[_locale_for(query)].format(
        verified_ddl=verified_ddl,
        question=query.question,
        max_rows=query.max_rows,
        engine=schema.engine.value,
    )


def build_fix_sql_prompt(
    schema: DatabaseSchema,
    query: EdaQuery,
    bad_sql: str,
    error: str,
    verified_ddl: str,
) -> str:
    return FIX_SQL[_locale_for(query)].format(
        question=query.question,
        verified_ddl=verified_ddl,
        bad_sql=bad_sql,
        error=error,
        max_rows=query.max_rows,
        engine=schema.engine.value,
    )


def build_report_prompt(
    schema: DatabaseSchema,
    query: EdaQuery,
    results: list[dict[str, Any]],
) -> str:
    schema_ddl = schema.to_ddl_summary()
    results_json = json.dumps(results, default=str, ensure_ascii=False, indent=2)
    return REPORT[_locale_for(query)].format(
        schema_ddl=schema_ddl,
        question=query.question,
        results_json=results_json,
    )


def build_propose_questions_prompt(
    *,
    locale: Locale,
    db_name: str,
    engine: str,
    verified_ddl: str,
    profile_summary: str,
) -> str:
    """Builder used by the explore flow (the agent passes the locale in)."""
    return PROPOSE_QUESTIONS[locale].format(
        db_name=db_name or ("desconocida" if locale == "es" else "unknown"),
        engine=engine,
        verified_ddl=verified_ddl,
        profile_summary=profile_summary,
    )


def build_summarize_db_prompt(
    *,
    locale: Locale,
    db_name: str,
    engine: str,
    total_tables: int,
    total_rows: int,
    table_summary: str,
    profile_summary: str,
) -> str:
    """Builder used by the explore flow's DB-summary node."""
    return SUMMARIZE_DB[locale].format(
        db_name=db_name or ("desconocida" if locale == "es" else "unknown"),
        engine=engine,
        total_tables=total_tables,
        total_rows=total_rows,
        table_summary=table_summary,
        profile_summary=profile_summary,
    )
