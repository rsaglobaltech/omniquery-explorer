"""Google Vertex AI adapter for Anthropic Claude.

Uses the official ``anthropic[vertex]`` client which talks to
``aiplatform.googleapis.com`` under the hood. Auth follows Application
Default Credentials (gcloud, service account JSON, workload identity).

Install with the optional extra: ``pip install 'omniquery-explorer[vertex]'``.
"""

from __future__ import annotations

import logging
from typing import Any

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


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "...<truncated>"


class VertexAdapter(LlmPort):
    """LlmPort implementation backed by Vertex AI + Claude."""

    def __init__(
        self,
        model: str,
        project: str,
        region: str = "us-east5",
        timeout: float = 120.0,
        max_retries: int = 3,
        max_tokens: int = 4096,
    ) -> None:
        # Defer the import — Vertex is an optional extra so users who
        # do not enable it must not pay the dependency cost.
        try:
            from anthropic import AsyncAnthropicVertex  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "LLM_PROVIDER=vertex requires the 'anthropic[vertex]' package. "
                "Install with: pip install 'omniquery-explorer[vertex]'"
            ) from exc

        self._model = model
        self._project = project
        self._region = region
        self._timeout = timeout
        self._max_retries = max_retries
        self._max_tokens = max_tokens
        self._system_prompt = load_system_prompt()
        # The Vertex client wraps Google ADC; if creds are missing it
        # raises at first call, which the retry loop will surface.
        self._client = AsyncAnthropicVertex(
            project_id=project, region=region, timeout=timeout
        )

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
                build_table_selection_prompt(schema, query),
                call_name="table_selection",
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
            build_report_prompt(schema, query, results),
            call_name="generate_report",
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _chat(self, user_content: str, *, call_name: str) -> str:
        # The Anthropic SDK shape mirrors the public Messages API, so
        # we use the same payload skeleton as the Anthropic adapter.
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": [{"role": "user", "content": user_content}],
        }
        if self._system_prompt:
            kwargs["system"] = self._system_prompt

        with span(
            "llm.call",
            provider="vertex",
            model=self._model,
            region=self._region,
            call_name=call_name,
        ):
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self._max_retries),
                wait=wait_exponential(multiplier=1, min=1, max=10),
                # Anthropic SDK exceptions inherit Exception; we keep
                # the retry filter broad so transient 5xx / quota
                # bursts get a second chance.
                retry=retry_if_exception_type(Exception),
                reraise=True,
            ):
                with attempt:
                    message = await self._client.messages.create(**kwargs)

        try:
            content = "".join(
                getattr(block, "text", "")
                for block in message.content
                if getattr(block, "type", None) == "text"
            ).strip()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"Unexpected Vertex/Anthropic response: {message}"
            ) from exc

        usage = getattr(message, "usage", None)
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
                    "provider": "vertex",
                    "region": self._region,
                    "call_name": call_name,
                },
                "tokens": {
                    "prompt_tokens": getattr(usage, "input_tokens", None),
                    "completion_tokens": getattr(usage, "output_tokens", None),
                    "total_tokens": (
                        (getattr(usage, "input_tokens", 0) or 0)
                        + (getattr(usage, "output_tokens", 0) or 0)
                    )
                    or None,
                },
                "input": {"prompt": _truncate(user_content, limit)},
                "output": {"response": _truncate(content, limit)},
            },
        )
        return content
