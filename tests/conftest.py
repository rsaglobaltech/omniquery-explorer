"""
Shared pytest fixtures for the omniquery test-suite.
"""
from __future__ import annotations

import math

import pytest

from omniquery.domain.entities.column import Column, ForeignKey
from omniquery.domain.entities.database_schema import DatabaseSchema, EngineType
from omniquery.domain.entities.table import Table
from omniquery.domain.entities.table_profile import TableProfile
from omniquery.domain.ports.outbound.embedding_port import EmbeddingPort

# ---------------------------------------------------------------------------
# Helpers / fake adapters
# ---------------------------------------------------------------------------

def _unit_vec(dim: int, hot_index: int) -> list[float]:
    """Return a unit vector with 1.0 at *hot_index* and 0.0 elsewhere."""
    v = [0.0] * dim
    v[hot_index] = 1.0
    return v


def _normalise(v: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in v))
    if norm == 0:
        return v
    return [x / norm for x in v]


class DeterministicEmbeddingPort(EmbeddingPort):
    """
    Fake EmbeddingPort whose vectors are fully deterministic.

    The embedding for a text is a unit vector in a 16-dimensional space.
    The dimension chosen is based on the hash of the text modulo 16, which
    makes it easy to reason about similarity in tests.

    You can also override specific texts via the *overrides* dict:
        { "some text": [0.1, 0.2, ...] }
    """

    DIM = 16

    def __init__(self, overrides: dict[str, list[float]] | None = None) -> None:
        self._overrides = overrides or {}
        self.embed_calls: list[str] = []
        self.embed_batch_calls: list[list[str]] = []

    def _vector(self, text: str) -> list[float]:
        if text in self._overrides:
            return self._overrides[text]
        index = hash(text) % self.DIM
        return _unit_vec(self.DIM, abs(index))

    async def embed(self, text: str) -> list[float]:
        self.embed_calls.append(text)
        return self._vector(text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self.embed_batch_calls.append(list(texts))
        return [self._vector(t) for t in texts]


# ---------------------------------------------------------------------------
# Schema fixtures
# ---------------------------------------------------------------------------

def _make_column(
    name: str,
    sql_type: str = "VARCHAR(255)",
    *,
    is_primary_key: bool = False,
    foreign_key: ForeignKey | None = None,
) -> Column:
    return Column(
        name=name,
        sql_type=sql_type,
        nullable=not is_primary_key,
        is_primary_key=is_primary_key,
        foreign_key=foreign_key,
    )


@pytest.fixture()
def simple_schema() -> DatabaseSchema:
    """
    Minimal e-commerce schema:

        customers (pk: customer_id)
        orders    (pk: order_id, fk: customer_id → customers)
        products  (pk: product_id)
        order_items (pk: item_id, fk: order_id → orders, product_id → products)
    """
    customers = Table(
        name="customers",
        columns=[
            _make_column("customer_id", "INTEGER", is_primary_key=True),
            _make_column("name", "VARCHAR(100)"),
            _make_column("email", "VARCHAR(255)"),
            _make_column("created_at", "TIMESTAMP"),
        ],
    )
    orders = Table(
        name="orders",
        columns=[
            _make_column("order_id", "INTEGER", is_primary_key=True),
            _make_column(
                "customer_id",
                "INTEGER",
                foreign_key=ForeignKey("customers", "customer_id"),
            ),
            _make_column("total_amount", "DECIMAL(10,2)"),
            _make_column("order_date", "DATE"),
        ],
    )
    products = Table(
        name="products",
        columns=[
            _make_column("product_id", "INTEGER", is_primary_key=True),
            _make_column("name", "VARCHAR(255)"),
            _make_column("price", "DECIMAL(10,2)"),
        ],
    )
    order_items = Table(
        name="order_items",
        columns=[
            _make_column("item_id", "INTEGER", is_primary_key=True),
            _make_column(
                "order_id",
                "INTEGER",
                foreign_key=ForeignKey("orders", "order_id"),
            ),
            _make_column(
                "product_id",
                "INTEGER",
                foreign_key=ForeignKey("products", "product_id"),
            ),
            _make_column("quantity", "INTEGER"),
        ],
    )
    return DatabaseSchema(
        engine=EngineType.POSTGRESQL,
        db_name="ecommerce",
        tables=[customers, orders, products, order_items],
    )


@pytest.fixture()
def simple_profiles() -> dict[str, TableProfile]:
    return {
        "customers": TableProfile(
            table_name="customers",
            row_count=5_000,
            has_dates=True,
            has_metrics=False,
            null_counts={"email": 50},
        ),
        "orders": TableProfile(
            table_name="orders",
            row_count=20_000,
            has_dates=True,
            has_metrics=True,
            null_counts={},
        ),
        "products": TableProfile(
            table_name="products",
            row_count=300,
            has_dates=False,
            has_metrics=True,
            null_counts={},
        ),
        "order_items": TableProfile(
            table_name="order_items",
            row_count=60_000,
            has_dates=False,
            has_metrics=True,
            null_counts={},
        ),
    }
