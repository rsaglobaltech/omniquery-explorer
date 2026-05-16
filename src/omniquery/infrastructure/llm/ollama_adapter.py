from __future__ import annotations

import json
import logging
import re
import textwrap
from pathlib import Path
from typing import Any

import httpx

from omniquery.domain.entities.database_schema import DatabaseSchema
from omniquery.domain.entities.eda_query import EdaQuery
from omniquery.domain.ports.outbound.llm_port import LlmPort
from omniquery.infrastructure.logging.agent_observability import get_log_context, get_payload_limit
from omniquery.infrastructure.observability.tracing import span

# Matches anything that is not a SELECT at the top of the LLM response
_NON_SELECT = re.compile(
    r"^\s*(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE)\b",
    re.IGNORECASE,
)

# Extracts table names after FROM / JOIN keywords (handles aliases)
_TABLE_REF = re.compile(
    r"\b(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_]*)(?:\s+(?:AS\s+)?[a-zA-Z_][a-zA-Z0-9_]*)?",
    re.IGNORECASE,
)

_SYSTEM_PROMPT_PATH = Path(__file__).parents[4] / "docs" / "system_prompt.md"
logger = logging.getLogger(__name__)


def _extract_table_names(sql: str) -> list[str]:
    """Return unique table names referenced after FROM / JOIN in a SQL statement."""
    return list(dict.fromkeys(m.group(1) for m in _TABLE_REF.finditer(sql)))


def _load_system_prompt() -> str:
    if _SYSTEM_PROMPT_PATH.exists():
        return _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    return ""  # Graceful fallback if path changes


def _extract_usage(payload: dict[str, Any]) -> dict[str, Any]:
    prompt_tokens = payload.get("prompt_eval_count")
    completion_tokens = payload.get("eval_count")
    total_tokens = None
    if isinstance(prompt_tokens, int) and isinstance(completion_tokens, int):
        total_tokens = prompt_tokens + completion_tokens
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "total_duration_ns": payload.get("total_duration"),
        "prompt_eval_duration_ns": payload.get("prompt_eval_duration"),
        "completion_eval_duration_ns": payload.get("eval_duration"),
    }


def _truncate_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "...<truncated>"


class OllamaAdapter(LlmPort):
    """
    Driven adapter that communicates with a locally-running Ollama instance.

    Ollama REST API:
        POST http://localhost:11434/api/chat
        Body: { model, messages: [{role, content}], stream: false }

    The adapter injects the database schema and query results into the
    message using the <schema_definition> / <query_results> tags defined
    in docs/system_prompt.md, keeping the LlmPort contract fully satisfied.

    Args:
        model:    Ollama model name (default: "llama3").
        base_url: Ollama server base URL (default: "http://localhost:11434").
        timeout:  HTTP timeout in seconds (default: 120).
    """

    def __init__(
        self,
        model: str = "llama3.2:latest",
        base_url: str = "http://localhost:11434",
        timeout: float = 300.0,
    ) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._system_prompt = _load_system_prompt()

    # ------------------------------------------------------------------
    # LlmPort implementation
    # ------------------------------------------------------------------

    async def chat(self, prompt: str, *, call_name: str = "chat") -> str:
        return await self._chat(prompt, call_name=call_name)

    async def generate_sql(self, schema: DatabaseSchema, query: EdaQuery) -> str:
        # ── Phase A: table selection ──────────────────────────────────────────
        # If semantic hint_tables are already provided (P1 schema linking),
        # skip the LLM selection step and use them directly.
        if query.hint_tables:
            valid_tables = [t for t in query.hint_tables if schema.get_table(t) is not None]
        else:
            # Give the LLM a compact list of ALL table names and let it pick the
            # most relevant ones *before* seeing any column details.  This prevents
            # it from inventing columns it never saw.
            all_table_names = "\n".join(f"- {n}" for n in schema.table_names)

            selection_prompt = textwrap.dedent(f"""
                You have a {schema.engine.value} database called '{schema.db_name}'.
                Here is the full list of tables:

                {all_table_names}

                Question: {query.question}

                Which 3 to 6 tables are most relevant to answer this question?
                Reply with ONLY a plain comma-separated list of table names — nothing else.
                Example: rna, taxonomy, xref
            """).strip()

            raw_tables = await self._chat(selection_prompt, call_name="table_selection")
            selected = [t.strip() for t in raw_tables.replace("\n", ",").split(",") if t.strip()]
            # Verify each selected table actually exists in the schema
            valid_tables = [t for t in selected if schema.get_table(t) is not None]

        # Fallback: use the generic DDL summary
        if not valid_tables:
            verified_ddl = schema.to_ddl_summary()
        else:
            verified_ddl = schema.exact_ddl(valid_tables)

        # ── Phase B: SQL generation ───────────────────────────────────────────
        user_message = textwrap.dedent(f"""
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

        raw = await self._chat(user_message, call_name="generate_sql")
        sql = self._extract_sql(raw)
        self._assert_select_only(sql)
        return sql

    async def generate_report(
        self,
        schema: DatabaseSchema,
        query: EdaQuery,
        results: list[dict[str, Any]],
    ) -> str:
        schema_ddl = schema.to_ddl_summary()
        results_json = json.dumps(results, default=str, ensure_ascii=False, indent=2)

        user_message = textwrap.dedent(f"""
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

        return await self._chat(user_message, call_name="generate_report")

    async def fix_sql(
        self,
        schema: DatabaseSchema,
        query: EdaQuery,
        bad_sql: str,
        error: str,
    ) -> str:
        # Extract every table name referenced in the failed SQL so we can inject
        # their *exact* verified columns, preventing the model from hallucinating.
        referenced = _extract_table_names(bad_sql)
        verified_ddl = schema.exact_ddl(referenced) if referenced else schema.to_ddl_summary()

        user_message = textwrap.dedent(f"""
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

        raw = await self._chat(user_message, call_name="fix_sql")
        sql = self._extract_sql(raw)
        self._assert_select_only(sql)
        return sql

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _chat(self, user_content: str, call_name: str = "chat") -> str:
        text, _ = await self._chat_with_meta(user_content, call_name=call_name)
        return text

    async def _chat_with_meta(
        self, user_content: str, call_name: str = "chat"
    ) -> tuple[str, dict[str, Any]]:
        payload = {
            "model": self._model,
            "stream": False,
            "messages": [
                {"role": "system", "content": self._system_prompt},
                {"role": "user", "content": user_content},
            ],
        }

        with span(
            "llm.call", provider="ollama", model=self._model, call_name=call_name
        ):
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._base_url}/api/chat", json=payload
                )
                response.raise_for_status()

        data = response.json()
        usage = _extract_usage(data)
        try:
            content = data["message"]["content"].strip()
        except (KeyError, TypeError) as exc:
            raise RuntimeError(
                f"Unexpected Ollama response structure: {data}"
            ) from exc
        log_ctx = get_log_context()
        payload_limit = get_payload_limit()
        logger.info(
            "LLM call completed",
            extra={
                "session_id": log_ctx.get("session_id"),
                "agent": log_ctx.get("agent", "llm"),
                "event": "llm_call",
                "context": {"model": self._model, "call_name": call_name},
                "tokens": usage,
                "input": {"prompt": _truncate_text(user_content, payload_limit)},
                "output": {"response": _truncate_text(content, payload_limit)},
            },
        )
        return content, usage

    @staticmethod
    def _extract_sql(text: str) -> str:
        """Strip markdown fences the model may wrap around the SQL."""
        # Remove ```sql ... ``` or ``` ... ```
        cleaned = re.sub(r"```(?:sql)?\s*(.*?)```", r"\1", text, flags=re.DOTALL)
        return cleaned.strip()

    @staticmethod
    def _assert_select_only(sql: str) -> None:
        if _NON_SELECT.match(sql):
            raise ValueError(
                f"LLM returned a non-SELECT statement: {sql[:120]!r}"
            )
