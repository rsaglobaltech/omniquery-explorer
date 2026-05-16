"""
Unit tests for SchemaGraphService:
  - build_graph: nodes, edges, FK attributes
  - compute_centrality: PageRank scores, fallback to in-degree
  - score_tables: composite scoring, top-N, factor contributions
  - _semantic_score helper
"""
from __future__ import annotations

import networkx as nx
import pytest

from omniquery.domain.entities.column import Column, ForeignKey
from omniquery.domain.entities.database_schema import DatabaseSchema, EngineType
from omniquery.domain.entities.table import Table
from omniquery.domain.entities.table_profile import TableProfile
from omniquery.infrastructure.graph.schema_graph_service import (
    SchemaGraphService,
    _semantic_score,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _col(name: str, fk: ForeignKey | None = None) -> Column:
    return Column(name=name, sql_type="INT", foreign_key=fk)


def _table(name: str, cols: list[Column]) -> Table:
    return Table(name=name, columns=cols)


def _schema(*tables: Table) -> DatabaseSchema:
    return DatabaseSchema(
        engine=EngineType.POSTGRESQL,
        db_name="test",
        tables=list(tables),
    )


def _profile(name: str, rows: int = 0, has_dates=False, has_metrics=False) -> TableProfile:
    return TableProfile(table_name=name, row_count=rows, has_dates=has_dates, has_metrics=has_metrics)


# ---------------------------------------------------------------------------
# _semantic_score
# ---------------------------------------------------------------------------

class TestSemanticScore:
    @pytest.mark.parametrize("name", [
        "users", "customers", "orders", "products", "transactions",
        "events", "sessions", "logs",
    ])
    def test_known_core_words_score_one(self, name: str):
        assert _semantic_score(name) == 1.0

    @pytest.mark.parametrize("name", ["xref_p1", "tmp_foo", "temp_bar", "stg_data", "bak_old"])
    def test_partition_staging_tables_score_zero(self, name: str):
        assert _semantic_score(name) == 0.0

    def test_mixed_case_insensitive(self):
        assert _semantic_score("ORDERS") == 1.0

    def test_partial_match_in_name(self):
        # "customer_details" contains "customer"
        assert _semantic_score("customer_details") == 1.0

    def test_unknown_table_scores_zero(self):
        assert _semantic_score("dim_geo_region") == 0.0


# ---------------------------------------------------------------------------
# build_graph
# ---------------------------------------------------------------------------

class TestBuildGraph:
    def test_all_tables_are_nodes(self):
        schema = _schema(
            _table("customers", [_col("id")]),
            _table("orders", [_col("id")]),
        )
        svc = SchemaGraphService()
        G = svc.build_graph(schema)
        assert set(G.nodes) >= {"customers", "orders"}

    def test_fk_creates_directed_edge_child_to_parent(self):
        schema = _schema(
            _table("customers", [_col("id")]),
            _table("orders", [
                _col("id"),
                _col("customer_id", ForeignKey("customers", "id")),
            ]),
        )
        svc = SchemaGraphService()
        G = svc.build_graph(schema)
        assert G.has_edge("orders", "customers")
        assert not G.has_edge("customers", "orders")

    def test_edge_carries_fk_col_attribute(self):
        schema = _schema(
            _table("customers", [_col("id")]),
            _table("orders", [
                _col("id"),
                _col("customer_id", ForeignKey("customers", "id")),
            ]),
        )
        G = SchemaGraphService().build_graph(schema)
        assert G["orders"]["customers"]["fk_col"] == "customer_id"

    def test_multiple_fks_from_same_table(self):
        schema = _schema(
            _table("customers", [_col("id")]),
            _table("products", [_col("id")]),
            _table("order_items", [
                _col("id"),
                _col("cid", ForeignKey("customers", "id")),
                _col("pid", ForeignKey("products", "id")),
            ]),
        )
        G = SchemaGraphService().build_graph(schema)
        assert G.has_edge("order_items", "customers")
        assert G.has_edge("order_items", "products")

    def test_no_fk_means_no_edges(self):
        schema = _schema(_table("standalone", [_col("id")]))
        G = SchemaGraphService().build_graph(schema)
        assert G.number_of_edges() == 0

    def test_empty_schema_produces_empty_graph(self):
        schema = DatabaseSchema(engine=EngineType.POSTGRESQL, db_name="x", tables=[])
        G = SchemaGraphService().build_graph(schema)
        assert G.number_of_nodes() == 0
        assert G.number_of_edges() == 0


# ---------------------------------------------------------------------------
# compute_centrality
# ---------------------------------------------------------------------------

class TestComputeCentrality:
    def test_returns_score_for_every_node(self):
        schema = _schema(
            _table("a", [_col("id")]),
            _table("b", [_col("a_id", ForeignKey("a", "id"))]),
        )
        svc = SchemaGraphService()
        G = svc.build_graph(schema)
        scores = svc.compute_centrality(G)
        assert set(scores.keys()) == {"a", "b"}

    def test_scores_sum_to_approximately_one(self):
        schema = _schema(
            _table("a", [_col("id")]),
            _table("b", [_col("a_id", ForeignKey("a", "id"))]),
            _table("c", [_col("a_id", ForeignKey("a", "id"))]),
        )
        svc = SchemaGraphService()
        G = svc.build_graph(schema)
        scores = svc.compute_centrality(G)
        assert sum(scores.values()) == pytest.approx(1.0, rel=1e-3)

    def test_referenced_table_has_higher_centrality(self):
        """'customers' is referenced by 'orders'; it should rank higher."""
        schema = _schema(
            _table("customers", [_col("id")]),
            _table("orders", [_col("cid", ForeignKey("customers", "id"))]),
        )
        svc = SchemaGraphService()
        G = svc.build_graph(schema)
        scores = svc.compute_centrality(G)
        assert scores["customers"] >= scores["orders"]

    def test_empty_graph_returns_empty_dict(self):
        svc = SchemaGraphService()
        assert svc.compute_centrality(nx.DiGraph()) == {}

    def test_all_scores_are_non_negative(self):
        schema = _schema(
            _table("a", [_col("id")]),
            _table("b", [_col("a_id", ForeignKey("a", "id"))]),
        )
        svc = SchemaGraphService()
        G = svc.build_graph(schema)
        scores = svc.compute_centrality(G)
        assert all(v >= 0 for v in scores.values())


# ---------------------------------------------------------------------------
# score_tables  (uses simple_schema + simple_profiles from conftest)
# ---------------------------------------------------------------------------

class TestScoreTables:
    def test_returns_scored_table_objects(self, simple_schema, simple_profiles):
        svc = SchemaGraphService()
        G = svc.build_graph(simple_schema)
        results = svc.score_tables(simple_schema, simple_profiles, G)
        assert results
        for st in results:
            assert hasattr(st, "table_name")
            assert hasattr(st, "score")

    def test_results_sorted_descending(self, simple_schema, simple_profiles):
        svc = SchemaGraphService()
        G = svc.build_graph(simple_schema)
        results = svc.score_tables(simple_schema, simple_profiles, G)
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_top_n_limits_results(self, simple_schema, simple_profiles):
        svc = SchemaGraphService()
        G = svc.build_graph(simple_schema)
        results = svc.score_tables(simple_schema, simple_profiles, G, top_n=2)
        assert len(results) == 2

    def test_scores_in_valid_range(self, simple_schema, simple_profiles):
        svc = SchemaGraphService()
        G = svc.build_graph(simple_schema)
        results = svc.score_tables(simple_schema, simple_profiles, G)
        for st in results:
            assert 0.0 <= st.score <= 1.0 + 1e-9  # allow tiny float error

    def test_high_row_count_boosts_score(self, simple_schema, simple_profiles):
        """order_items has 60k rows — should score higher than products (300 rows)."""
        svc = SchemaGraphService()
        G = svc.build_graph(simple_schema)
        results = svc.score_tables(simple_schema, simple_profiles, G)
        by_name = {r.table_name: r.score for r in results}
        assert by_name["order_items"] > by_name["products"]

    def test_table_with_dates_and_metrics_boosted(self, simple_schema, simple_profiles):
        """orders has both dates and metrics; score should reflect it."""
        svc = SchemaGraphService()
        G = svc.build_graph(simple_schema)
        results = svc.score_tables(simple_schema, simple_profiles, G)
        orders = next(r for r in results if r.table_name == "orders")
        assert "has metrics" in orders.reasons
        assert "has dates" in orders.reasons

    def test_missing_profile_treated_gracefully(self, simple_schema):
        """If profiling data is absent the service should not raise."""
        svc = SchemaGraphService()
        G = svc.build_graph(simple_schema)
        results = svc.score_tables(simple_schema, {}, G)  # empty profiles
        assert len(results) == len(simple_schema.tables)

    def test_centrality_included_in_scored_table(self, simple_schema, simple_profiles):
        svc = SchemaGraphService()
        G = svc.build_graph(simple_schema)
        results = svc.score_tables(simple_schema, simple_profiles, G)
        for st in results:
            assert st.centrality >= 0.0
