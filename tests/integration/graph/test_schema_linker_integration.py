"""
Integration tests for SchemaLinker — no mocking of the EmbeddingPort;
uses the DeterministicEmbeddingPort from conftest.py to exercise the full
ranking pipeline end-to-end without external I/O.

These tests verify:
  - The full embed → rank pipeline produces correct, stable results.
  - The cache survives across multiple questions on the same schema.
  - Multiple schemas do not share the same cache partition.
  - Adding new candidate tables triggers incremental embedding (not full re-embed).
  - Ranking improves specificity when candidate_tables narrows the search space.
"""
from __future__ import annotations

import pytest

from omniquery.domain.entities.column import Column, ForeignKey
from omniquery.domain.entities.database_schema import DatabaseSchema, EngineType
from omniquery.domain.entities.table import Table
from omniquery.infrastructure.graph.schema_linker import SchemaLinker
from tests.conftest import DeterministicEmbeddingPort

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DIM = 16  # must match DeterministicEmbeddingPort.DIM


def _unit(idx: int) -> list[float]:
    v = [0.0] * DIM
    v[abs(idx) % DIM] = 1.0
    return v


def _ecommerce_schema() -> DatabaseSchema:
    tables = [
        Table("customers",   [Column("customer_id", "INT"), Column("email", "VARCHAR")]),
        Table("orders",      [Column("order_id", "INT"), Column("customer_id", "INT",
                               foreign_key=ForeignKey("customers", "customer_id"))]),
        Table("products",    [Column("product_id", "INT"), Column("price", "DECIMAL")]),
        Table("order_items", [Column("item_id", "INT"),
                              Column("order_id", "INT", foreign_key=ForeignKey("orders", "order_id")),
                              Column("product_id", "INT", foreign_key=ForeignKey("products", "product_id"))]),
        Table("reviews",     [Column("review_id", "INT"), Column("rating", "INT")]),
    ]
    return DatabaseSchema(engine=EngineType.POSTGRESQL, db_name="shop", tables=tables)


def _desc(schema: DatabaseSchema, table_name: str) -> str:
    t = schema.get_table(table_name)
    if t is None:
        return table_name
    col_names = ", ".join(c.name for c in t.columns[:30])
    return f"{table_name}: {col_names}"


def _make_port(schema: DatabaseSchema, question: str, target_table: str) -> DeterministicEmbeddingPort:
    """
    Return a DeterministicEmbeddingPort where:
      - Every table description maps to a unique orthogonal axis.
      - The question vector is identical to the target_table description vector,
        guaranteeing cosine similarity = 1.0 for that table.
    """
    overrides: dict[str, list[float]] = {}
    for i, table in enumerate(schema.tables):
        desc = _desc(schema, table.name)
        overrides[desc] = _unit(i)
    # Make question identical to target table's vector
    target_desc = _desc(schema, target_table)
    overrides[question] = overrides[target_desc]
    return DeterministicEmbeddingPort(overrides=overrides)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSchemaLinkerIntegration:
    @pytest.mark.asyncio
    async def test_top_1_is_most_similar_table(self):
        schema = _ecommerce_schema()
        port = _make_port(schema, "Show all customer emails", "customers")
        linker = SchemaLinker(port)
        result = await linker.rank_tables(schema, "Show all customer emails", top_k=1)
        assert result == ["customers"]

    @pytest.mark.asyncio
    async def test_top_3_includes_target(self):
        schema = _ecommerce_schema()
        port = _make_port(schema, "What are the top products by revenue?", "products")
        linker = SchemaLinker(port)
        result = await linker.rank_tables(schema, "What are the top products by revenue?", top_k=3)
        assert "products" in result

    @pytest.mark.asyncio
    async def test_cache_persists_across_questions(self):
        schema = _ecommerce_schema()
        port = _make_port(schema, "q1", "orders")
        linker = SchemaLinker(port)

        await linker.rank_tables(schema, "q1", top_k=3)
        batch_calls_after_first = len(port.embed_batch_calls)

        # Second question on same schema → cache hit, no new embed_batch
        await linker.rank_tables(schema, "q2", top_k=3)
        assert len(port.embed_batch_calls) == batch_calls_after_first

    @pytest.mark.asyncio
    async def test_two_schemas_have_separate_caches(self):
        schema_a = _ecommerce_schema()
        schema_b = DatabaseSchema(
            engine=EngineType.MYSQL,
            db_name="analytics",
            tables=[Table("events", [Column("event_id", "INT")])],
        )
        port_a = _make_port(schema_a, "q", "orders")
        port_b = DeterministicEmbeddingPort()

        linker_a = SchemaLinker(port_a)
        linker_b = SchemaLinker(port_b)

        await linker_a.rank_tables(schema_a, "q", top_k=2)
        await linker_b.rank_tables(schema_b, "q", top_k=1)

        # Each linker should have cached only its own schema
        from omniquery.infrastructure.graph.schema_linker import _schema_key
        assert _schema_key(schema_a) in linker_a._cache
        assert _schema_key(schema_b) not in linker_a._cache

    @pytest.mark.asyncio
    async def test_candidate_tables_reduces_result_set(self):
        schema = _ecommerce_schema()
        port = _make_port(schema, "q", "orders")
        linker = SchemaLinker(port)

        candidates = ["orders", "order_items"]
        result = await linker.rank_tables(schema, "q", top_k=5, candidate_tables=candidates)
        assert set(result).issubset(set(candidates))

    @pytest.mark.asyncio
    async def test_incremental_embedding_for_new_candidates(self):
        """
        First call caches tables A, B, C.
        Second call adds table D as an extra candidate — only D should be
        embedded in the new batch, not A/B/C again.
        """
        schema = _ecommerce_schema()
        port = _make_port(schema, "q", "products")
        linker = SchemaLinker(port)

        await linker.rank_tables(schema, "q", top_k=2, candidate_tables=["customers", "orders"])
        calls_after_first = len(port.embed_batch_calls)
        total_texts_first = sum(len(c) for c in port.embed_batch_calls)

        # Second call introduces "products" which wasn't embedded yet
        await linker.rank_tables(schema, "q", top_k=3, candidate_tables=["customers", "orders", "products"])
        calls_after_second = len(port.embed_batch_calls)
        total_texts_second = sum(len(c) for c in port.embed_batch_calls)

        # A new batch was triggered for the incremental table
        assert calls_after_second > calls_after_first
        # Only 1 new text was embedded (products description)
        new_texts = total_texts_second - total_texts_first
        assert new_texts == 1

    @pytest.mark.asyncio
    async def test_full_pipeline_returns_ordered_list(self):
        schema = _ecommerce_schema()
        # Build a port where all tables get distinct vectors and the question
        # points exactly at "reviews"
        port = _make_port(schema, "Show me all user reviews", "reviews")
        linker = SchemaLinker(port)
        result = await linker.rank_tables(schema, "Show me all user reviews", top_k=5)
        assert result[0] == "reviews"
        assert len(result) == 5
        assert result == sorted(result, key=lambda t: (
            # Replicate the expected ordering: reviews first, rest any order
            0 if t == "reviews" else 1
        ))
