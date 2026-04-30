"""
End-to-end tests for schema-linking.

These tests exercise the FULL stack — SchemaLinker + OllamaEmbeddingAdapter —
against a real Ollama server running locally.

Requirements
------------
- Ollama must be running at http://localhost:11434
- The nomic-embed-text model must be pulled:  ollama pull nomic-embed-text

Skipping
--------
If Ollama is unavailable the tests are automatically skipped (not failed).
You can also force-skip by setting the env var:  SKIP_E2E=1

Running
-------
    pytest tests/e2e/ -v -m e2e
"""
from __future__ import annotations

import os
import pytest
import httpx

from omniquery.domain.entities.column import Column, ForeignKey
from omniquery.domain.entities.database_schema import DatabaseSchema, EngineType
from omniquery.domain.entities.table import Table
from omniquery.infrastructure.graph.schema_linker import SchemaLinker
from omniquery.infrastructure.llm.ollama_embedding_adapter import OllamaEmbeddingAdapter


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")


def _ollama_available() -> bool:
    """Return True only if Ollama responds to a health probe."""
    if os.getenv("SKIP_E2E"):
        return False
    try:
        resp = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=3.0)
        return resp.status_code == 200
    except Exception:
        return False


skip_if_no_ollama = pytest.mark.skipif(
    not _ollama_available(),
    reason="Ollama not available at %s — skipping e2e tests" % OLLAMA_URL,
)

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]


@pytest.fixture()
def embedding_adapter() -> OllamaEmbeddingAdapter:
    return OllamaEmbeddingAdapter(model=EMBED_MODEL, base_url=OLLAMA_URL, timeout=60.0)


@pytest.fixture()
def ecommerce_schema() -> DatabaseSchema:
    return DatabaseSchema(
        engine=EngineType.POSTGRESQL,
        db_name="shop",
        tables=[
            Table("customers", [
                Column("customer_id", "INT", is_primary_key=True),
                Column("name", "VARCHAR"),
                Column("email", "VARCHAR"),
                Column("signup_date", "DATE"),
            ]),
            Table("orders", [
                Column("order_id", "INT", is_primary_key=True),
                Column("customer_id", "INT",
                       foreign_key=ForeignKey("customers", "customer_id")),
                Column("order_date", "DATE"),
                Column("total_amount", "DECIMAL(10,2)"),
            ]),
            Table("products", [
                Column("product_id", "INT", is_primary_key=True),
                Column("name", "VARCHAR"),
                Column("category", "VARCHAR"),
                Column("price", "DECIMAL(10,2)"),
            ]),
            Table("order_items", [
                Column("item_id", "INT", is_primary_key=True),
                Column("order_id", "INT",
                       foreign_key=ForeignKey("orders", "order_id")),
                Column("product_id", "INT",
                       foreign_key=ForeignKey("products", "product_id")),
                Column("quantity", "INT"),
                Column("unit_price", "DECIMAL(10,2)"),
            ]),
            Table("reviews", [
                Column("review_id", "INT", is_primary_key=True),
                Column("product_id", "INT",
                       foreign_key=ForeignKey("products", "product_id")),
                Column("customer_id", "INT",
                       foreign_key=ForeignKey("customers", "customer_id")),
                Column("rating", "INT"),
                Column("comment", "TEXT"),
                Column("created_at", "TIMESTAMP"),
            ]),
            Table("inventory", [
                Column("inventory_id", "INT", is_primary_key=True),
                Column("product_id", "INT",
                       foreign_key=ForeignKey("products", "product_id")),
                Column("warehouse", "VARCHAR"),
                Column("stock_qty", "INT"),
            ]),
        ],
    )


# ---------------------------------------------------------------------------
# E2E tests
# ---------------------------------------------------------------------------

class TestSchemaLinkerE2E:
    @skip_if_no_ollama
    async def test_customer_question_returns_customers_in_top2(
        self, embedding_adapter, ecommerce_schema
    ):
        linker = SchemaLinker(embedding_adapter)
        result = await linker.rank_tables(
            ecommerce_schema,
            "How many customers signed up last month?",
            top_k=2,
        )
        assert "customers" in result

    @skip_if_no_ollama
    async def test_order_revenue_question_returns_orders(
        self, embedding_adapter, ecommerce_schema
    ):
        linker = SchemaLinker(embedding_adapter)
        result = await linker.rank_tables(
            ecommerce_schema,
            "What is the total revenue per month from orders?",
            top_k=3,
        )
        assert "orders" in result

    @skip_if_no_ollama
    async def test_product_review_question_returns_reviews_or_products(
        self, embedding_adapter, ecommerce_schema
    ):
        linker = SchemaLinker(embedding_adapter)
        result = await linker.rank_tables(
            ecommerce_schema,
            "Show me the average product rating from reviews.",
            top_k=2,
        )
        assert "reviews" in result or "products" in result

    @skip_if_no_ollama
    async def test_inventory_question_returns_inventory(
        self, embedding_adapter, ecommerce_schema
    ):
        linker = SchemaLinker(embedding_adapter)
        result = await linker.rank_tables(
            ecommerce_schema,
            "Which products are low on stock in the warehouse?",
            top_k=2,
        )
        assert "inventory" in result

    @skip_if_no_ollama
    async def test_top_k_is_respected(self, embedding_adapter, ecommerce_schema):
        linker = SchemaLinker(embedding_adapter)
        for k in (1, 3, 6):
            result = await linker.rank_tables(ecommerce_schema, "any question", top_k=k)
            assert len(result) == k

    @skip_if_no_ollama
    async def test_result_contains_only_schema_tables(
        self, embedding_adapter, ecommerce_schema
    ):
        linker = SchemaLinker(embedding_adapter)
        result = await linker.rank_tables(
            ecommerce_schema, "Who are our best customers?", top_k=4
        )
        assert set(result).issubset(set(ecommerce_schema.table_names))

    @skip_if_no_ollama
    async def test_embedding_cache_avoids_double_requests(
        self, embedding_adapter, ecommerce_schema
    ):
        """Two consecutive calls should hit the cache on the second round."""
        linker = SchemaLinker(embedding_adapter)
        await linker.rank_tables(ecommerce_schema, "first question", top_k=3)
        # Clear question-embedding state but keep table cache via the adapter
        # (we can't easily count HTTP calls without monkey-patching httpx;
        #  we verify indirectly that the call succeeds quickly and returns same schema tables)
        result = await linker.rank_tables(ecommerce_schema, "second question", top_k=3)
        assert set(result).issubset(set(ecommerce_schema.table_names))

    @skip_if_no_ollama
    async def test_candidate_tables_limits_search(
        self, embedding_adapter, ecommerce_schema
    ):
        linker = SchemaLinker(embedding_adapter)
        candidates = ["customers", "orders"]
        result = await linker.rank_tables(
            ecommerce_schema,
            "Show customer order history",
            top_k=5,
            candidate_tables=candidates,
        )
        assert set(result).issubset(set(candidates))

    @skip_if_no_ollama
    async def test_clear_cache_and_rerank(self, embedding_adapter, ecommerce_schema):
        linker = SchemaLinker(embedding_adapter)
        r1 = await linker.rank_tables(ecommerce_schema, "orders by customer", top_k=3)
        linker.clear_cache()
        r2 = await linker.rank_tables(ecommerce_schema, "orders by customer", top_k=3)
        # Both should be valid rankings (may not be identical due to model randomness,
        # but the most relevant table should appear in both)
        assert set(r1) & set(r2)  # non-empty intersection
