from __future__ import annotations

import logging
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from omniquery.domain.entities.database_schema import DatabaseSchema
from omniquery.domain.entities.eda_query import EdaQuery
from omniquery.domain.ports.outbound.llm_port import LlmPort
from omniquery.infrastructure.llm.llm_prompts import (
    assert_select_only,
    build_fix_sql_prompt,
    build_generate_sql_prompt,
    build_report_prompt,
    build_table_selection_prompt,
    extract_sql,
    extract_table_names,
    load_system_prompt,
)
from omniquery.infrastructure.logging.agent_observability import (
    get_log_context,
    get_payload_limit,
)
from omniquery.infrastructure.observability.tracing import span

logger = logging.getLogger(__name__)

_ANTHROPIC_VERSION = "2023-06-01"


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "...<truncated>"


class AnthropicAdapter(LlmPort):
    """Messages-API adapter for Anthropic Claude models."""

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str = "https://api.anthropic.com",
        timeout: float = 120.0,
        max_retries: int = 3,
        max_tokens: int = 4096,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max_retries
        self._max_tokens = max_tokens
        self._system_prompt = load_system_prompt()
        self._client = httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------
    # LlmPort
    # ------------------------------------------------------------------

    async def chat(self, prompt: str, *, call_name: str = "chat") -> str:
        return await self._chat(prompt, call_name=call_name)

    async def generate_sql(self, schema: DatabaseSchema, query: EdaQuery) -> str:
        if query.hint_tables:
            valid_tables = [t for t in query.hint_tables if schema.get_table(t) is not None]
        else:
            raw = await self._chat(
                build_table_selection_prompt(schema, query), call_name="table_selection"
            )
            selected = [t.strip() for t in raw.replace("\n", ",").split(",") if t.strip()]
            valid_tables = [t for t in selected if schema.get_table(t) is not None]

        verified_ddl = (
            schema.exact_ddl(valid_tables) if valid_tables else schema.to_ddl_summary()
        )
        raw = await self._chat(
            build_generate_sql_prompt(schema, query, verified_ddl),
            call_name="generate_sql",
        )
        sql = extract_sql(raw)
        assert_select_only(sql)
        return sql

    async def fix_sql(
        self,
        schema: DatabaseSchema,
        query: EdaQuery,
        bad_sql: str,
        error: str,
    ) -> str:
        referenced = extract_table_names(bad_sql)
        verified_ddl = (
            schema.exact_ddl(referenced) if referenced else schema.to_ddl_summary()
        )
        raw = await self._chat(
            build_fix_sql_prompt(schema, query, bad_sql, error, verified_ddl),
            call_name="fix_sql",
        )
        sql = extract_sql(raw)
        assert_select_only(sql)
        return sql

    async def generate_report(
        self,
        schema: DatabaseSchema,
        query: EdaQuery,
        results: list[dict[str, Any]],
    ) -> str:
        return await self._chat(
            build_report_prompt(schema, query, results), call_name="generate_report"
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _chat(self, user_content: str, *, call_name: str) -> str:
        payload: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": [{"role": "user", "content": user_content}],
        }
        if self._system_prompt:
            payload["system"] = self._system_prompt

        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

        with span(
            "llm.call",
            provider="anthropic",
            model=self._model,
            call_name=call_name,
        ):
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self._max_retries),
                wait=wait_exponential(multiplier=1, min=1, max=10),
                retry=retry_if_exception_type(
                    (httpx.HTTPStatusError, httpx.TransportError)
                ),
                reraise=True,
            ):
                with attempt:
                    response = await self._client.post(
                        f"{self._base_url}/v1/messages",
                        json=payload,
                        headers=headers,
                    )
                    response.raise_for_status()
                    data = response.json()

        try:
            parts = data["content"]
            content = "".join(
                p.get("text", "") for p in parts if p.get("type") == "text"
            ).strip()
        except (KeyError, TypeError) as exc:
            raise RuntimeError(
                f"Unexpected Anthropic response structure: {data}"
            ) from exc

        usage = data.get("usage", {})
        log_ctx = get_log_context()
        limit = get_payload_limit()
        logger.info(
            "LLM call completed",
            extra={
                "session_id": log_ctx.get("session_id"),
                "agent": log_ctx.get("agent", "llm"),
                "event": "llm_call",
                "context": {
                    "model": self._model,
                    "provider": "anthropic",
                    "call_name": call_name,
                },
                "tokens": {
                    "prompt_tokens": usage.get("input_tokens"),
                    "completion_tokens": usage.get("output_tokens"),
                    "total_tokens": (
                        (usage.get("input_tokens") or 0)
                        + (usage.get("output_tokens") or 0)
                    )
                    or None,
                },
                "input": {"prompt": _truncate(user_content, limit)},
                "output": {"response": _truncate(content, limit)},
            },
        )
        return content
