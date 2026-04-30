"""
Unit tests for SchemaLinker.rank_tables — all I/O is mocked or uses the
deterministic fake EmbeddingPort from conftest.py.

Focus:
  - Correct ranking by cosine similarity
  - top_k parameter is respected
  - candidate_tables filtering works
  - Embedding cache is used (embed_batch not called twice for same schema)
  - Fallback behaviour on embed_batch failure
  - Fallback behaviour on question-embedding failure
  - clear_cache wipes stored vectors
"""
from __future__ import annotations

import pytest

from omniquery.domain.entities.column import Column
from omniquery.domain.entities.database_schema import DatabaseSchema, EngineType
from omniquery.domain.entities.table import Table
from omniquery.domain.ports.outbound.embedding_port import EmbeddingPort
from omniquery.infrastructure.graph.schema_linker import SchemaLinker

# Re-use shared fixtures from tests/conftest.py
# (simple_schema, DeterministicEmbeddingPort are available via conftest)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unit(dim: int, idx: int) -> list[float]:
    v = [0.0] * dim
    v[idx] = 1.0
    return v


class FailOnBatchEmbeddingPort(EmbeddingPort):
    """Raises on embed_batch; embed works normally."""

    async def embed(self, text: str) -> list[float]:
        return _unit(4, 0)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("batch embed unavailable")


class FailOnQuestionEmbeddingPort(EmbeddingPort):
    """embed_batch works; embed (question) raises."""

    async def embed(self, text: str) -> list[float]:
        raise RuntimeError("question embed unavailable")

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [_unit(4, i % 4) for i in range(len(texts))]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def schema_4() -> DatabaseSchema:
    """Schema with 4 tables whose descriptions map to known unit vectors."""
    return DatabaseSchema(
        engine=EngineType.POSTGRESQL,
        db_name="demo",
        tables=[
            Table(name="orders", columns=[Column("order_id", "INT")]),
            Table(name="customers", columns=[Column("customer_id", "INT")]),
            Table(name="products", columns=[Column("product_id", "INT")]),
            Table(name="log_events", columns=[Column("event_id", "INT")]),
        ],
    )


@pytest.fixture()
def deterministic_port(schema_4):
    """
    EmbeddingPort where each table description and the question map to
    controlled unit vectors so cosine similarity is fully predictable.
    """
    from tests.conftest import DeterministicEmbeddingPort

    DIM = 4

    # Build deterministic descriptions matching the schema
    def _desc(table_name: str) -> str:
        t = schema_4.get_table(table_name)
        col_names = ", ".join(c.name for c in t.columns)
        return f"{table_name}: {col_names}"

    # Assign each table description a distinct orthogonal axis
    overrides = {
        _desc("orders"):     _unit(DIM, 0),
        _desc("customers"):  _unit(DIM, 1),
        _desc("products"):   _unit(DIM, 2),
        _desc("log_events"): _unit(DIM, 3),
        # Question vector closest to "orders"
        "Show me all orders": _unit(DIM, 0),
    }
    return DeterministicEmbeddingPort(overrides=overrides)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRankTables:
    @pytest.mark.asyncio
    async def test_top_table_matches_question(self, schema_4, deterministic_port):
        linker = SchemaLinker(deterministic_port)
        result = await linker.rank_tables(schema_4, "Show me all orders", top_k=1)
        assert result == ["orders"]

    @pytest.mark.asyncio
    async def test_top_k_limits_result_count(self, schema_4, deterministic_port):
        linker = SchemaLinker(deterministic_port)
        result = await linker.rank_tables(schema_4, "Show me all orders", top_k=2)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_top_k_larger_than_tables_returns_all(self, schema_4, deterministic_port):
        linker = SchemaLinker(deterministic_port)
        result = await linker.rank_tables(schema_4, "Show me all orders", top_k=100)
        assert len(result) == 4

    @pytest.mark.asyncio
    async def test_candidate_tables_restricts_search_space(self, schema_4, deterministic_port):
        linker = SchemaLinker(deterministic_port)
        candidates = ["customers", "products"]
        result = await linker.rank_tables(
            schema_4, "Show me all orders", top_k=5, candidate_tables=candidates
        )
        assert set(result).issubset(set(candidates))
        assert "orders" not in result

    @pytest.mark.asyncio
    async def test_result_contains_only_valid_table_names(self, schema_4, deterministic_port):
        linker = SchemaLinker(deterministic_port)
        result = await linker.rank_tables(schema_4, "Show me all orders", top_k=4)
        assert set(result).issubset(set(schema_4.table_names))

    @pytest.mark.asyncio
    async def test_embedding_cache_reused_on_second_call(self, schema_4, deterministic_port):
        linker = SchemaLinker(deterministic_port)
        await linker.rank_tables(schema_4, "Show me all orders", top_k=2)
        first_batch_calls = len(deterministic_port.embed_batch_calls)

        await linker.rank_tables(schema_4, "List customers", top_k=2)
        second_batch_calls = len(deterministic_port.embed_batch_calls)

        # embed_batch should NOT be called again for the same schema
        assert second_batch_calls == first_batch_calls

    @pytest.mark.asyncio
    async def test_clear_cache_forces_re_embed(self, schema_4, deterministic_port):
        linker = SchemaLinker(deterministic_port)
        await linker.rank_tables(schema_4, "Show me all orders", top_k=1)
        calls_before = len(deterministic_port.embed_batch_calls)

        linker.clear_cache(schema_4)
        await linker.rank_tables(schema_4, "Show me all orders", top_k=1)
        calls_after = len(deterministic_port.embed_batch_calls)

        assert calls_after > calls_before

    @pytest.mark.asyncio
    async def test_clear_all_cache(self, schema_4, deterministic_port):
        linker = SchemaLinker(deterministic_port)
        await linker.rank_tables(schema_4, "question", top_k=1)
        linker.clear_cache()  # clear all
        assert linker._cache == {}

    @pytest.mark.asyncio
    async def test_fallback_on_embed_batch_failure(self, schema_4):
        port = FailOnBatchEmbeddingPort()
        linker = SchemaLinker(port)
        result = await linker.rank_tables(schema_4, "any question", top_k=2)
        # Should return at most top_k tables in original order without crashing
        assert len(result) <= 2
        assert all(t in schema_4.table_names for t in result)

    @pytest.mark.asyncio
    async def test_fallback_on_question_embed_failure(self, schema_4):
        port = FailOnQuestionEmbeddingPort()
        linker = SchemaLinker(port)
        result = await linker.rank_tables(schema_4, "any question", top_k=2)
        assert len(result) <= 2
        assert all(t in schema_4.table_names for t in result)

    @pytest.mark.asyncio
    async def test_empty_schema_returns_empty_list(self):
        from tests.conftest import DeterministicEmbeddingPort

        empty_schema = DatabaseSchema(
            engine=EngineType.POSTGRESQL,
            db_name="empty",
            tables=[],
        )
        linker = SchemaLinker(DeterministicEmbeddingPort())
        result = await linker.rank_tables(empty_schema, "anything", top_k=5)
        assert result == []

    @pytest.mark.asyncio
    async def test_ranking_is_deterministic(self, schema_4, deterministic_port):
        linker = SchemaLinker(deterministic_port)
        r1 = await linker.rank_tables(schema_4, "Show me all orders", top_k=4)
        linker.clear_cache()
        r2 = await linker.rank_tables(schema_4, "Show me all orders", top_k=4)
        assert r1 == r2
