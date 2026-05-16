"""
Unit tests for the pure helper functions in schema_linker.py:

  - _cosine()
  - _table_description()
  - _schema_key()
"""
from __future__ import annotations

import math

import pytest

from omniquery.domain.entities.column import Column
from omniquery.domain.entities.database_schema import DatabaseSchema, EngineType
from omniquery.domain.entities.table import Table
from omniquery.infrastructure.graph.schema_linker import (
    _cosine,
    _schema_key,
    _table_description,
)

# ---------------------------------------------------------------------------
# _cosine
# ---------------------------------------------------------------------------


class TestCosine:
    def test_identical_vectors_returns_one(self):
        v = [1.0, 2.0, 3.0]
        assert _cosine(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors_returns_zero(self):
        a = [1.0, 0.0, 0.0]
        b = [0.0, 1.0, 0.0]
        assert _cosine(a, b) == pytest.approx(0.0)

    def test_opposite_vectors_returns_minus_one(self):
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert _cosine(a, b) == pytest.approx(-1.0)

    def test_zero_vector_a_returns_zero(self):
        a = [0.0, 0.0, 0.0]
        b = [1.0, 2.0, 3.0]
        assert _cosine(a, b) == pytest.approx(0.0)

    def test_zero_vector_b_returns_zero(self):
        a = [1.0, 2.0, 3.0]
        b = [0.0, 0.0, 0.0]
        assert _cosine(a, b) == pytest.approx(0.0)

    def test_both_zero_vectors_returns_zero(self):
        a = [0.0, 0.0]
        b = [0.0, 0.0]
        assert _cosine(a, b) == pytest.approx(0.0)

    def test_similarity_is_symmetric(self):
        a = [1.0, 2.0, 3.0]
        b = [4.0, 5.0, 6.0]
        assert _cosine(a, b) == pytest.approx(_cosine(b, a))

    def test_similarity_between_zero_and_one_for_positive_vectors(self):
        a = [1.0, 2.0]
        b = [3.0, 1.0]
        result = _cosine(a, b)
        assert 0.0 <= result <= 1.0

    def test_known_value(self):
        # cos([1,1], [1,0]) = 1/sqrt(2) ≈ 0.7071
        a = [1.0, 1.0]
        b = [1.0, 0.0]
        expected = 1.0 / math.sqrt(2)
        assert _cosine(a, b) == pytest.approx(expected, rel=1e-6)

    def test_scaled_vector_same_direction(self):
        """Scaling a vector should not change cosine similarity."""
        a = [1.0, 2.0, 3.0]
        b = [2.0, 4.0, 6.0]  # 2 * a
        assert _cosine(a, b) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# _table_description
# ---------------------------------------------------------------------------


def _make_table(name: str, col_names: list[str], comment: str | None = None) -> Table:
    columns = [Column(name=c, sql_type="VARCHAR") for c in col_names]
    return Table(name=name, columns=columns, comment=comment)


def _schema_with(*tables: Table) -> DatabaseSchema:
    return DatabaseSchema(
        engine=EngineType.POSTGRESQL,
        db_name="test_db",
        tables=list(tables),
    )


class TestTableDescription:
    def test_basic_format(self):
        schema = _schema_with(_make_table("orders", ["order_id", "customer_id", "amount"]))
        desc = _table_description(schema, "orders")
        assert desc == "orders: order_id, customer_id, amount"

    def test_includes_comment_when_present(self):
        schema = _schema_with(
            _make_table("orders", ["order_id"], comment="Main orders table")
        )
        desc = _table_description(schema, "orders")
        assert " — Main orders table" in desc
        assert desc.startswith("orders")

    def test_unknown_table_returns_name(self):
        schema = _schema_with(_make_table("orders", ["order_id"]))
        desc = _table_description(schema, "non_existent")
        assert desc == "non_existent"

    def test_truncates_to_30_columns(self):
        cols = [f"col_{i}" for i in range(50)]
        schema = _schema_with(_make_table("big_table", cols))
        desc = _table_description(schema, "big_table")
        listed_cols = desc.split(": ", 1)[1].split(", ")
        assert len(listed_cols) == 30

    def test_empty_columns(self):
        schema = _schema_with(Table(name="empty_table", columns=[]))
        desc = _table_description(schema, "empty_table")
        assert "empty_table" in desc


# ---------------------------------------------------------------------------
# _schema_key
# ---------------------------------------------------------------------------


class TestSchemaKey:
    def test_key_includes_engine_and_db_name(self):
        schema = _schema_with(_make_table("t", ["c"]))
        schema.db_name = "mydb"
        key = _schema_key(schema)
        assert "postgresql" in key
        assert "mydb" in key

    def test_different_table_counts_produce_different_keys(self):
        s1 = _schema_with(_make_table("a", ["c"]))
        s2 = _schema_with(_make_table("a", ["c"]), _make_table("b", ["c"]))
        assert _schema_key(s1) != _schema_key(s2)

    def test_same_schema_produces_same_key(self):
        s = _schema_with(_make_table("t", ["c"]))
        assert _schema_key(s) == _schema_key(s)
