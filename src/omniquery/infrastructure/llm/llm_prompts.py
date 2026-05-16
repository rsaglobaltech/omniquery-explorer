"""Prompt builders shared by all chat-style LLM adapters.

Keeps generate_sql / fix_sql / generate_report prompts in one place so
the OpenAI, Anthropic, and Ollama adapters stay thin transports.
"""

from __future__ import annotations

import json
import re
import textwrap
from pathlib import Path
from typing import Any

from omniquery.domain.entities.database_schema import DatabaseSchema
from omniquery.domain.entities.eda_query import EdaQuery

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


def build_table_selection_prompt(schema: DatabaseSchema, query: EdaQuery) -> str:
    all_table_names = "\n".join(f"- {n}" for n in schema.table_names)
    return textwrap.dedent(f"""
        You have a {schema.engine.value} database called '{schema.db_name}'.
        Here is the full list of tables:

        {all_table_names}

        Question: {query.question}

        Which 3 to 6 tables are most relevant to answer this question?
        Reply with ONLY a plain comma-separated list of table names — nothing else.
        Example: rna, taxonomy, xref
    """).strip()


def build_generate_sql_prompt(
    schema: DatabaseSchema, query: EdaQuery, verified_ddl: str
) -> str:
    return textwrap.dedent(f"""
        VERIFIED SCHEMA — use ONLY these tables and their exact columns:
        {verified_ddl}

        Question: {query.question}

        Rules:
        - Use ONLY column names that appear in the VERIFIED SCHEMA above.
        - Do NOT invent column names or table names.
        - Only join on columns that exist in BOTH tables.
        - Reply with ONLY the SQL SELECT statement — no explanation, no markdown fences.
        - Maximum {query.max_rows} rows (add LIMIT as appropriate for {schema.engine.value}).
    """).strip()


def build_fix_sql_prompt(
    schema: DatabaseSchema,
    query: EdaQuery,
    bad_sql: str,
    error: str,
    verified_ddl: str,
) -> str:
    return textwrap.dedent(f"""
        The following SQL statement was generated for the question:
        "{query.question}"

        It raised a database error. You MUST fix it using ONLY the exact
        column names listed in the VERIFIED SCHEMA below.
        DO NOT use any column name that is not explicitly listed there.
        DO NOT invent JOIN conditions — only join on columns that exist in BOTH tables.

        VERIFIED SCHEMA (authoritative — do not deviate):
        {verified_ddl}

        FAILED SQL:
        {bad_sql}

        DATABASE ERROR:
        {error}

        Reply with ONLY the corrected SQL SELECT statement — no explanation,
        no markdown fences.
        Maximum {query.max_rows} rows (add LIMIT as appropriate for
        {schema.engine.value}).
    """).strip()


def build_report_prompt(
    schema: DatabaseSchema,
    query: EdaQuery,
    results: list[dict[str, Any]],
) -> str:
    schema_ddl = schema.to_ddl_summary()
    results_json = json.dumps(results, default=str, ensure_ascii=False, indent=2)
    return textwrap.dedent(f"""
        <schema_definition>
        {schema_ddl}
        </schema_definition>

        Original question: {query.question}

        <query_results>
        {results_json}
        </query_results>

        Generate the full EDA report following the output format defined in your
        system prompt (sections: 🧠 Análisis del Negocio, 🔍 Estrategia SQL,
        📊 Análisis Exploratorio, 📝 Conclusiones).
    """).strip()
