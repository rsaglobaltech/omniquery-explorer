"""
Integration tests for SchemaGraphService — full graph build + centrality +
scoring pipeline with a realistic multi-table schema.

No mocking; exercises the real NetworkX algorithms with controlled data.
"""
from __future__ import annotations

import pytest

from omniquery.domain.entities.column import Column, ForeignKey
from omniquery.domain.entities.database_schema import DatabaseSchema, EngineType
from omniquery.domain.entities.table import Table
from omniquery.domain.entities.table_profile import TableProfile
from omniquery.infrastructure.graph.schema_graph_service import SchemaGraphService


# ---------------------------------------------------------------------------
# Shared schema: airline reservation system
# ---------------------------------------------------------------------------

@pytest.fixture()
def airline_schema() -> DatabaseSchema:
    """
    airports ← flights → airlines
    flights  ← bookings → passengers
    bookings ← payments
    """
    return DatabaseSchema(
        engine=EngineType.POSTGRESQL,
        db_name="airline",
        tables=[
            Table("airports", [
                Column("airport_id", "INT", is_primary_key=True),
                Column("code", "CHAR(3)"),
                Column("city", "VARCHAR"),
            ]),
            Table("airlines", [
                Column("airline_id", "INT", is_primary_key=True),
                Column("name", "VARCHAR"),
            ]),
            Table("flights", [
                Column("flight_id", "INT", is_primary_key=True),
                Column("origin_id", "INT", foreign_key=ForeignKey("airports", "airport_id")),
                Column("dest_id", "INT", foreign_key=ForeignKey("airports", "airport_id")),
                Column("airline_id", "INT", foreign_key=ForeignKey("airlines", "airline_id")),
                Column("departure_time", "TIMESTAMP"),
                Column("price", "DECIMAL(10,2)"),
            ]),
            Table("passengers", [
                Column("passenger_id", "INT", is_primary_key=True),
                Column("name", "VARCHAR"),
                Column("email", "VARCHAR"),
            ]),
            Table("bookings", [
                Column("booking_id", "INT", is_primary_key=True),
                Column("flight_id", "INT", foreign_key=ForeignKey("flights", "flight_id")),
                Column("passenger_id", "INT", foreign_key=ForeignKey("passengers", "passenger_id")),
                Column("booked_at", "TIMESTAMP"),
                Column("total_paid", "DECIMAL(10,2)"),
            ]),
            Table("payments", [
                Column("payment_id", "INT", is_primary_key=True),
                Column("booking_id", "INT", foreign_key=ForeignKey("bookings", "booking_id")),
                Column("amount", "DECIMAL(10,2)"),
                Column("paid_at", "TIMESTAMP"),
            ]),
        ],
    )


@pytest.fixture()
def airline_profiles() -> dict[str, TableProfile]:
    return {
        "airports":   TableProfile("airports",   row_count=500,    has_dates=False, has_metrics=False),
        "airlines":   TableProfile("airlines",   row_count=50,     has_dates=False, has_metrics=False),
        "flights":    TableProfile("flights",    row_count=200_000, has_dates=True,  has_metrics=True),
        "passengers": TableProfile("passengers", row_count=150_000, has_dates=False, has_metrics=False),
        "bookings":   TableProfile("bookings",   row_count=300_000, has_dates=True,  has_metrics=True),
        "payments":   TableProfile("payments",   row_count=280_000, has_dates=True,  has_metrics=True),
    }


# ---------------------------------------------------------------------------
# Tests: build_graph
# ---------------------------------------------------------------------------

class TestBuildGraphIntegration:
    def test_all_six_tables_are_nodes(self, airline_schema):
        svc = SchemaGraphService()
        G = svc.build_graph(airline_schema)
        assert set(G.nodes) >= set(airline_schema.table_names)

    def test_flights_points_to_airports_and_airlines(self, airline_schema):
        G = SchemaGraphService().build_graph(airline_schema)
        assert G.has_edge("flights", "airports")
        assert G.has_edge("flights", "airlines")

    def test_bookings_points_to_flights_and_passengers(self, airline_schema):
        G = SchemaGraphService().build_graph(airline_schema)
        assert G.has_edge("bookings", "flights")
        assert G.has_edge("bookings", "passengers")

    def test_payments_points_to_bookings(self, airline_schema):
        G = SchemaGraphService().build_graph(airline_schema)
        assert G.has_edge("payments", "bookings")

    def test_no_self_loops(self, airline_schema):
        G = SchemaGraphService().build_graph(airline_schema)
        assert not any(u == v for u, v in G.edges)


# ---------------------------------------------------------------------------
# Tests: compute_centrality
# ---------------------------------------------------------------------------

class TestComputeCentralityIntegration:
    def test_airports_at_least_as_central_as_airlines(self, airline_schema):
        """airports has 2 incoming FK edges from flights; airlines only 1.
        airports centrality should be >= airlines centrality."""
        svc = SchemaGraphService()
        G = svc.build_graph(airline_schema)
        scores = svc.compute_centrality(G)
        assert scores["airports"] >= scores["airlines"]

    def test_all_tables_have_centrality_score(self, airline_schema):
        svc = SchemaGraphService()
        G = svc.build_graph(airline_schema)
        scores = svc.compute_centrality(G)
        assert set(scores.keys()) == set(airline_schema.table_names)

    def test_leaf_tables_have_lower_centrality_than_hubs(self, airline_schema):
        """payments references only bookings → lower centrality than airports/bookings."""
        svc = SchemaGraphService()
        G = svc.build_graph(airline_schema)
        scores = svc.compute_centrality(G)
        # airports is referenced by flights (twice) and bookings indirectly
        assert scores.get("airports", 0) > scores.get("payments", 0)


# ---------------------------------------------------------------------------
# Tests: score_tables (full pipeline)
# ---------------------------------------------------------------------------

class TestScoreTablesIntegration:
    def test_bookings_in_top3(self, airline_schema, airline_profiles):
        """bookings has 300k rows, dates, metrics → should rank highly."""
        svc = SchemaGraphService()
        G = svc.build_graph(airline_schema)
        results = svc.score_tables(airline_schema, airline_profiles, G, top_n=6)
        top3 = [r.table_name for r in results[:3]]
        assert "bookings" in top3

    def test_airlines_not_in_top3(self, airline_schema, airline_profiles):
        """airlines has only 50 rows and no metrics → should rank lower."""
        svc = SchemaGraphService()
        G = svc.build_graph(airline_schema)
        results = svc.score_tables(airline_schema, airline_profiles, G, top_n=6)
        top3 = [r.table_name for r in results[:3]]
        assert "airlines" not in top3

    def test_score_is_reproducible(self, airline_schema, airline_profiles):
        """Calling score_tables twice should return the same ranking."""
        svc = SchemaGraphService()
        G = svc.build_graph(airline_schema)
        r1 = svc.score_tables(airline_schema, airline_profiles, G, top_n=6)
        r2 = svc.score_tables(airline_schema, airline_profiles, G, top_n=6)
        assert [t.table_name for t in r1] == [t.table_name for t in r2]

    def test_reason_list_populated(self, airline_schema, airline_profiles):
        svc = SchemaGraphService()
        G = svc.build_graph(airline_schema)
        results = svc.score_tables(airline_schema, airline_profiles, G)
        # At least some tables should have non-empty reasons
        tables_with_reasons = [r for r in results if r.reasons]
        assert tables_with_reasons

    def test_top_n_respected(self, airline_schema, airline_profiles):
        svc = SchemaGraphService()
        G = svc.build_graph(airline_schema)
        results = svc.score_tables(airline_schema, airline_profiles, G, top_n=3)
        assert len(results) == 3

    def test_high_row_count_improves_rank(self, airline_schema, airline_profiles):
        """bookings (300k) should rank higher than airports (500)."""
        svc = SchemaGraphService()
        G = svc.build_graph(airline_schema)
        results = svc.score_tables(airline_schema, airline_profiles, G, top_n=6)
        rank = {r.table_name: i for i, r in enumerate(results)}
        assert rank["bookings"] < rank["airports"]
