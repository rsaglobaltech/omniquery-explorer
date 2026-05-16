"""
Schema Linker — semantic table selection via embedding similarity.

Given a natural-language question and a DatabaseSchema, the SchemaLinker
embeds short descriptions of every table (name + column names) and ranks
them by cosine similarity to the question embedding.  The top-k results
replace (or augment) the LLM-based table selection phase so the SQL
generator sees only the most relevant subset of the schema.
"""
from __future__ import annotations

import logging
import math
from collections.abc import Sequence

from omniquery.domain.entities.database_schema import DatabaseSchema
from omniquery.domain.ports.outbound.embedding_port import EmbeddingPort

logger = logging.getLogger(__name__)


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _table_description(schema: DatabaseSchema, table_name: str) -> str:
    """
    Build a compact text description of a table suitable for embedding.

    Example:
        "orders: order_id, customer_id, total_amount, created_at, status"
    """
    table = schema.get_table(table_name)
    if table is None:
        return table_name
    col_names = ", ".join(c.name for c in table.columns[:30])
    comment = f" — {table.comment}" if table.comment else ""
    return f"{table_name}{comment}: {col_names}"


class SchemaLinker:
    """
    Semantic schema linking service.

    Workflow:
        1. Build a dict {table_name: embedding} for all (or top-N) tables.
        2. Embed the user question.
        3. Rank tables by cosine similarity; return the top-k names.

    The embeddings are built lazily (on first call) and cached per database
    schema identity to avoid redundant API calls during a single session.
    """

    def __init__(self, embedding_port: EmbeddingPort) -> None:
        self._emb = embedding_port
        # Cache: schema identity → {table_name: vector}
        self._cache: dict[str, dict[str, list[float]]] = {}

    async def rank_tables(
        self,
        schema: DatabaseSchema,
        question: str,
        top_k: int = 6,
        candidate_tables: Sequence[str] | None = None,
    ) -> list[str]:
        """
        Return up to `top_k` table names most relevant to `question`.

        Args:
            schema:           The introspected database schema.
            question:         Natural language question.
            top_k:            Number of tables to return.
            candidate_tables: If provided, only consider these tables
                              (e.g. the output of an earlier LLM selection).
                              Falls back to all schema tables.

        Returns:
            Ordered list of table names (most relevant first).
        """
        table_names = list(candidate_tables) if candidate_tables else schema.table_names

        # Build / retrieve table embeddings
        cache_key = _schema_key(schema)
        if cache_key not in self._cache:
            self._cache[cache_key] = {}

        table_emb_cache = self._cache[cache_key]
        missing = [n for n in table_names if n not in table_emb_cache]
        if missing:
            descriptions = [_table_description(schema, n) for n in missing]
            try:
                vectors = await self._emb.embed_batch(descriptions)
                for name, vec in zip(missing, vectors):
                    table_emb_cache[name] = vec
            except Exception as exc:
                logger.warning(
                    "[schema_linker] Embedding failed, falling back to original order: %s", exc
                )
                return list(table_names[:top_k])

        # Embed the question
        try:
            q_vec = await self._emb.embed(question)
        except Exception as exc:
            logger.warning(
                "[schema_linker] Question embedding failed, falling back to original order: %s", exc
            )
            return list(table_names[:top_k])

        # Rank by cosine similarity
        scored = [
            (n, _cosine(q_vec, table_emb_cache[n]))
            for n in table_names
            if n in table_emb_cache
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        result = [name for name, _ in scored[:top_k]]
        logger.debug("[schema_linker] top-%d tables for %r: %s", top_k, question[:60], result)
        return result

    def clear_cache(self, schema: DatabaseSchema | None = None) -> None:
        """Clear embedding cache (all schemas or a specific one)."""
        if schema is None:
            self._cache.clear()
        else:
            self._cache.pop(_schema_key(schema), None)


def _schema_key(schema: DatabaseSchema) -> str:
    """Derive a stable cache key from the schema's identity."""
    return f"{schema.engine.value}:{schema.db_name}:{len(schema.tables)}"
