from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from omniquery.domain.entities.database_schema import DatabaseSchema
from omniquery.domain.entities.eda_query import EdaQuery


class LlmPort(ABC):
    """
    Outbound port — defines the contract every LLM adapter must fulfil.

    The domain layer calls only these two methods; the concrete adapter
    (OllamaAdapter, OpenAIAdapter, …) handles transport, auth, and
    prompt serialisation transparently.
    """

    @abstractmethod
    async def generate_sql(
        self,
        schema: DatabaseSchema,
        query: EdaQuery,
    ) -> str:
        """
        Translate a natural language question into a safe SELECT statement.

        The implementation is responsible for injecting the schema inside
        <schema_definition> tags as specified in docs/system_prompt.md.

        Args:
            schema: The introspected database schema.
            query:  The user's EdaQuery value object.

        Returns:
            A single, syntactically valid SELECT statement (no trailing semicolon
            required, but allowed).

        Raises:
            ValueError: If the LLM returns a non-SELECT statement.
            RuntimeError: On transport / model errors.
        """

    @abstractmethod
    async def fix_sql(
        self,
        schema: DatabaseSchema,
        query: EdaQuery,
        bad_sql: str,
        error: str,
    ) -> str:
        """
        Ask the LLM to correct a SQL statement that raised a DB error.

        Args:
            schema:  The introspected database schema.
            query:   The original EdaQuery.
            bad_sql: The SQL statement that failed.
            error:   The database error message returned by the engine.

        Returns:
            A corrected SELECT statement.

        Raises:
            ValueError: If the LLM still returns a non-SELECT statement.
            RuntimeError: On transport / model errors.
        """

    @abstractmethod
    async def chat(self, prompt: str, *, call_name: str = "chat") -> str:
        """
        Free-form single-turn chat completion. Used by orchestration
        agents (question proposal, DB summarisation) that do not need
        schema-bound prompts.

        Args:
            prompt:     The user prompt sent to the model.
            call_name:  Tag used by observability layer to identify the
                        purpose of the call (e.g. ``propose_questions``).

        Returns:
            The model's plain-text completion.
        """

    @abstractmethod
    async def generate_report(
        self,
        schema: DatabaseSchema,
        query: EdaQuery,
        results: list[dict[str, Any]],
    ) -> str:
        """
        Produce a Markdown EDA report from the SQL results.

        The implementation injects results inside <query_results> tags
        as specified in docs/system_prompt.md.

        Args:
            schema:  The introspected database schema.
            query:   The original EdaQuery.
            results: Rows returned by execute_query.

        Returns:
            A Markdown string ready for rendering in the CLI or Web UI.
        """
