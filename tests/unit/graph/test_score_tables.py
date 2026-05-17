from __future__ import annotations

from omniquery.domain.entities.database_schema import DatabaseSchema, EngineType
from omniquery.domain.entities.table_profile import TableProfile
from omniquery.infrastructure.graph.schema_graph_service import SchemaGraphService


def test_score_tables_orders_by_volume_and_centrality(
    simple_schema: DatabaseSchema,
    simple_profiles: dict[str, TableProfile],
) -> None:
    """Larger + more-referenced tables must outrank small leaf tables."""
    svc = SchemaGraphService()
    G = svc.build_graph(simple_schema)
    scored = svc.score_tables(simple_schema, simple_profiles, G, top_n=4)

    # All four tables present in the ranking.
    names = [s.table_name for s in scored]
    assert sorted(names) == ["customers", "order_items", "orders", "products"]

    # order_items has the largest row count (60k) so it should top the list,
    # ahead of orders (20k), customers (5k), products (300).
    ranked = [s.table_name for s in scored]
    assert ranked.index("order_items") < ranked.index("products")
    assert ranked.index("orders") < ranked.index("products")


def test_score_tables_reasons_include_volume_and_metrics(
    simple_schema: DatabaseSchema,
    simple_profiles: dict[str, TableProfile],
) -> None:
    svc = SchemaGraphService()
    G = svc.build_graph(simple_schema)
    scored = svc.score_tables(simple_schema, simple_profiles, G, top_n=4)

    order_items = next(s for s in scored if s.table_name == "order_items")
    joined = " · ".join(order_items.reasons)
    assert "rows" in joined
    assert "metrics" in joined


def test_score_tables_handles_missing_profiles() -> None:
    """Tables without a profile must still be ranked (with f_quality=0.5)."""
    schema = DatabaseSchema(
        engine=EngineType.SQLITE,
        db_name="empty",
        tables=[],
    )
    svc = SchemaGraphService()
    G = svc.build_graph(schema)
    scored = svc.score_tables(schema, {}, G, top_n=5)
    assert scored == []
