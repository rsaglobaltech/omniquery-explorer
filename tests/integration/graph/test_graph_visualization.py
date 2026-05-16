"""
Visualization tests for SchemaGraphService.

These tests build real graphs and render them to PNG files under
``tests/artifacts/``.  They are fast (pure CPU, no I/O to DBs or LLMs)
and always pass — the assertion is only that the image file is created
with a non-zero size, so you can open it and inspect it.

Run with:
    uv run pytest tests/integration/graph/test_graph_visualization.py -v -s

Outputs (relative to repo root):
    tests/artifacts/fk_graph_airline.png     — annotated FK directed-graph
    tests/artifacts/fk_graph_ecommerce.png   — second schema for comparison
    tests/artifacts/score_ranking.png        — horizontal bar chart of scores
    tests/artifacts/dashboard.png            — 3-panel composite dashboard
"""
from __future__ import annotations

import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")          # headless — no display required
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import matplotlib.colors as mcolors
import networkx as nx
import pytest

from omniquery.domain.entities.column import Column, ForeignKey
from omniquery.domain.entities.database_schema import DatabaseSchema, EngineType
from omniquery.domain.entities.table import Table
from omniquery.domain.entities.table_profile import TableProfile
from omniquery.infrastructure.graph.schema_graph_service import SchemaGraphService


# ---------------------------------------------------------------------------
# Output directory
# ---------------------------------------------------------------------------

ARTIFACTS = Path(__file__).parents[2] / "artifacts"


@pytest.fixture(scope="module", autouse=True)
def ensure_artifacts_dir():
    ARTIFACTS.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Shared airline schema + profiles  (same domain as service integration tests)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def airline_schema() -> DatabaseSchema:
    """
    Airline reservation system:
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
                Column("dest_id",   "INT", foreign_key=ForeignKey("airports", "airport_id")),
                Column("airline_id","INT", foreign_key=ForeignKey("airlines", "airline_id")),
                Column("departure_time", "TIMESTAMP"),
                Column("price", "DECIMAL(10,2)"),
            ]),
            Table("passengers", [
                Column("passenger_id", "INT", is_primary_key=True),
                Column("name", "VARCHAR"),
                Column("email", "VARCHAR"),
            ]),
            Table("bookings", [
                Column("booking_id",   "INT", is_primary_key=True),
                Column("flight_id",    "INT", foreign_key=ForeignKey("flights",    "flight_id")),
                Column("passenger_id", "INT", foreign_key=ForeignKey("passengers", "passenger_id")),
                Column("booked_at",    "TIMESTAMP"),
                Column("total_paid",   "DECIMAL(10,2)"),
            ]),
            Table("payments", [
                Column("payment_id", "INT", is_primary_key=True),
                Column("booking_id", "INT", foreign_key=ForeignKey("bookings", "booking_id")),
                Column("amount",     "DECIMAL(10,2)"),
                Column("paid_at",    "TIMESTAMP"),
            ]),
        ],
    )


@pytest.fixture(scope="module")
def airline_profiles() -> dict[str, TableProfile]:
    return {
        "airports":   TableProfile("airports",   row_count=500,     has_dates=False, has_metrics=False),
        "airlines":   TableProfile("airlines",   row_count=50,      has_dates=False, has_metrics=False),
        "flights":    TableProfile("flights",    row_count=200_000, has_dates=True,  has_metrics=True),
        "passengers": TableProfile("passengers", row_count=150_000, has_dates=False, has_metrics=False),
        "bookings":   TableProfile("bookings",   row_count=300_000, has_dates=True,  has_metrics=True),
        "payments":   TableProfile("payments",   row_count=280_000, has_dates=True,  has_metrics=True),
    }


# ---------------------------------------------------------------------------
# Minimal e-commerce schema
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def ecommerce_schema() -> DatabaseSchema:
    return DatabaseSchema(
        engine=EngineType.POSTGRESQL,
        db_name="ecommerce",
        tables=[
            Table("customers",   [Column("customer_id", "INT", is_primary_key=True),
                                  Column("email", "VARCHAR"), Column("created_at", "TIMESTAMP")]),
            Table("products",    [Column("product_id", "INT", is_primary_key=True),
                                  Column("price", "DECIMAL(10,2)")]),
            Table("orders",      [Column("order_id", "INT", is_primary_key=True),
                                  Column("customer_id", "INT", foreign_key=ForeignKey("customers", "customer_id")),
                                  Column("total_amount", "DECIMAL(10,2)"), Column("order_date", "DATE")]),
            Table("order_items", [Column("item_id", "INT", is_primary_key=True),
                                  Column("order_id",   "INT", foreign_key=ForeignKey("orders",   "order_id")),
                                  Column("product_id", "INT", foreign_key=ForeignKey("products", "product_id")),
                                  Column("quantity", "INT")]),
            Table("reviews",     [Column("review_id", "INT", is_primary_key=True),
                                  Column("customer_id", "INT", foreign_key=ForeignKey("customers", "customer_id")),
                                  Column("rating", "INT"), Column("reviewed_at", "TIMESTAMP")]),
        ],
    )


@pytest.fixture(scope="module")
def ecommerce_profiles() -> dict[str, TableProfile]:
    return {
        "customers":   TableProfile("customers",   row_count=5_000,  has_dates=True,  has_metrics=False),
        "products":    TableProfile("products",    row_count=300,    has_dates=False, has_metrics=True),
        "orders":      TableProfile("orders",      row_count=20_000, has_dates=True,  has_metrics=True),
        "order_items": TableProfile("order_items", row_count=60_000, has_dates=False, has_metrics=True),
        "reviews":     TableProfile("reviews",     row_count=8_000,  has_dates=True,  has_metrics=True),
    }


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------

_CMAP = cm.RdYlGn   # low score → red, high score → green


def _draw_fk_graph(
    schema: DatabaseSchema,
    profiles: dict[str, TableProfile],
    output_path: Path,
    title: str = "FK Schema Graph",
) -> None:
    """
    Render a styled directed FK graph with:
      - Node size  ∝ log(row_count + 1)
      - Node color ∝ composite importance score  (RdYlGn colormap)
      - Edge labels: FK column name
      - Node labels: table name + score
    """
    svc = SchemaGraphService()
    G = svc.build_graph(schema)
    scored = svc.score_tables(schema, profiles, G, top_n=len(schema.tables))
    score_map = {s.table_name: s.score for s in scored}
    row_map   = {s.table_name: s.row_count for s in scored}

    # ── Layout ──────────────────────────────────────────────────────────────
    pos = nx.spring_layout(G, seed=42, k=2.5)

    # ── Node visuals ─────────────────────────────────────────────────────────
    node_scores = [score_map.get(n, 0.0) for n in G.nodes]
    node_sizes  = [
        max(800, 400 * math.log1p(row_map.get(n, 0) / 1000))
        for n in G.nodes
    ]
    norm   = mcolors.Normalize(vmin=0.0, vmax=max(node_scores, default=1.0))
    colors = [_CMAP(norm(s)) for s in node_scores]

    # ── Edge labels ──────────────────────────────────────────────────────────
    edge_labels = {
        (u, v): data.get("fk_col", "")
        for u, v, data in G.edges(data=True)
    }

    # ── Node labels with score ────────────────────────────────────────────────
    node_labels = {n: f"{n}\n({score_map.get(n, 0):.3f})" for n in G.nodes}

    # ── Draw ─────────────────────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(14, 9))
    ax.set_title(title, fontsize=15, fontweight="bold", pad=16)
    ax.axis("off")

    nx.draw_networkx_nodes(G, pos, node_color=colors, node_size=node_sizes,
                           alpha=0.92, ax=ax)
    nx.draw_networkx_labels(G, pos, labels=node_labels, font_size=8,
                            font_weight="bold", ax=ax)
    nx.draw_networkx_edges(G, pos, edge_color="#555555", arrows=True,
                           arrowstyle="-|>", arrowsize=22,
                           connectionstyle="arc3,rad=0.08",
                           min_source_margin=20, min_target_margin=20,
                           width=1.6, ax=ax)
    nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels,
                                 font_size=7, font_color="#333333",
                                 bbox=dict(boxstyle="round,pad=0.2",
                                           fc="white", alpha=0.6),
                                 ax=ax)

    # ── Colorbar ─────────────────────────────────────────────────────────────
    sm = cm.ScalarMappable(cmap=_CMAP, norm=norm)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, shrink=0.55, pad=0.01)
    cbar.set_label("Composite importance score", fontsize=9)

    plt.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"\n  ✓ Graph saved → {output_path}")


def _draw_score_bar_chart(
    schema: DatabaseSchema,
    profiles: dict[str, TableProfile],
    output_path: Path,
    title: str = "Table Importance Scores",
) -> None:
    """
    Horizontal bar chart: one bar per table, colored by score,
    annotated with score value and reasons.
    """
    svc = SchemaGraphService()
    G = svc.build_graph(schema)
    scored = svc.score_tables(schema, profiles, G, top_n=len(schema.tables))
    # Lowest score at top (horizontal bar convention)
    scored_asc = list(reversed(scored))

    names   = [s.table_name for s in scored_asc]
    scores  = [s.score for s in scored_asc]
    reasons = [" · ".join(s.reasons) if s.reasons else "—" for s in scored_asc]

    norm   = mcolors.Normalize(vmin=0.0, vmax=max(scores, default=1.0))
    colors = [_CMAP(norm(s)) for s in scores]

    fig, ax = plt.subplots(figsize=(12, max(4, len(names) * 0.8)))
    bars = ax.barh(names, scores, color=colors, edgecolor="#444", linewidth=0.6)

    # Annotate bars
    for bar, score, reason in zip(bars, scores, reasons):
        ax.text(
            bar.get_width() + 0.005, bar.get_y() + bar.get_height() / 2,
            f"{score:.4f}  —  {reason}",
            va="center", ha="left", fontsize=8, color="#333333",
        )

    ax.set_xlim(0, max(scores, default=1.0) * 1.55)
    ax.set_xlabel("Composite score  (0 – 1)", fontsize=10)
    ax.set_title(title, fontsize=13, fontweight="bold", pad=12)
    ax.spines[["top", "right"]].set_visible(False)

    sm = cm.ScalarMappable(cmap=_CMAP, norm=norm)
    sm.set_array([])
    fig.colorbar(sm, ax=ax, shrink=0.6, pad=0.01)

    plt.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  ✓ Bar chart saved → {output_path}")


def _draw_dashboard(
    schema: DatabaseSchema,
    profiles: dict[str, TableProfile],
    output_path: Path,
    title: str = "Schema Graph Dashboard",
) -> None:
    """
    3-panel dashboard:
      Left  — FK directed graph (annotated)
      Top-R — composite score bar chart
      Bot-R — centrality bar chart (PageRank)
    """
    svc = SchemaGraphService()
    G = svc.build_graph(schema)
    scored = svc.score_tables(schema, profiles, G, top_n=len(schema.tables))
    centrality = svc.compute_centrality(G)

    score_map = {s.table_name: s.score for s in scored}
    row_map   = {s.table_name: s.row_count for s in scored}

    fig = plt.figure(figsize=(20, 10))
    fig.suptitle(f"{title}  —  db: {schema.db_name}", fontsize=15,
                 fontweight="bold", y=1.01)

    # ── Panel 1: FK graph ─────────────────────────────────────────────────────
    ax_graph = fig.add_axes([0.00, 0.0, 0.50, 1.0])
    ax_graph.set_title("FK Directed Graph\n(node size ∝ row count, color ∝ score)",
                       fontsize=10)
    ax_graph.axis("off")

    pos = nx.spring_layout(G, seed=42, k=2.5)
    node_scores = [score_map.get(n, 0.0) for n in G.nodes]
    node_sizes  = [max(900, 350 * math.log1p(row_map.get(n, 0) / 1000)) for n in G.nodes]
    norm        = mcolors.Normalize(vmin=0.0, vmax=max(node_scores, default=1.0))
    colors      = [_CMAP(norm(s)) for s in node_scores]
    edge_labels = {(u, v): d.get("fk_col", "") for u, v, d in G.edges(data=True)}
    node_labels = {n: f"{n}\n({score_map.get(n, 0):.3f})" for n in G.nodes}

    nx.draw_networkx_nodes(G, pos, node_color=colors, node_size=node_sizes,
                           alpha=0.9, ax=ax_graph)
    nx.draw_networkx_labels(G, pos, labels=node_labels, font_size=8,
                            font_weight="bold", ax=ax_graph)
    nx.draw_networkx_edges(G, pos, edge_color="#555", arrows=True,
                           arrowstyle="-|>", arrowsize=20,
                           connectionstyle="arc3,rad=0.08",
                           min_source_margin=18, min_target_margin=18,
                           width=1.5, ax=ax_graph)
    nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels,
                                 font_size=6.5, font_color="#333",
                                 bbox=dict(boxstyle="round,pad=0.15",
                                           fc="white", alpha=0.6),
                                 ax=ax_graph)

    # ── Panel 2: composite scores ─────────────────────────────────────────────
    ax_scores = fig.add_axes([0.53, 0.52, 0.45, 0.46])
    scored_asc = list(reversed(scored))
    s_names  = [s.table_name for s in scored_asc]
    s_values = [s.score for s in scored_asc]
    s_colors = [_CMAP(norm(v)) for v in s_values]
    ax_scores.barh(s_names, s_values, color=s_colors, edgecolor="#444", linewidth=0.5)
    for i, (n, v) in enumerate(zip(s_names, s_values)):
        ax_scores.text(v + 0.003, i, f"{v:.4f}", va="center", fontsize=8)
    ax_scores.set_xlim(0, max(s_values, default=1.0) * 1.4)
    ax_scores.set_title("Composite Importance Score", fontsize=10, fontweight="bold")
    ax_scores.set_xlabel("Score", fontsize=9)
    ax_scores.spines[["top", "right"]].set_visible(False)

    # ── Panel 3: PageRank centrality ─────────────────────────────────────────
    ax_cent = fig.add_axes([0.53, 0.04, 0.45, 0.42])
    sorted_central = sorted(centrality.items(), key=lambda x: x[1])
    c_names  = [k for k, _ in sorted_central]
    c_values = [v for _, v in sorted_central]
    norm_c   = mcolors.Normalize(vmin=0.0, vmax=max(c_values, default=1.0))
    c_colors = [cm.Blues(norm_c(v) * 0.8 + 0.2) for v in c_values]
    ax_cent.barh(c_names, c_values, color=c_colors, edgecolor="#444", linewidth=0.5)
    for i, (n, v) in enumerate(zip(c_names, c_values)):
        ax_cent.text(v + 0.001, i, f"{v:.4f}", va="center", fontsize=8)
    ax_cent.set_xlim(0, max(c_values, default=1.0) * 1.4)
    ax_cent.set_title("PageRank Centrality", fontsize=10, fontweight="bold")
    ax_cent.set_xlabel("PageRank score", fontsize=9)
    ax_cent.spines[["top", "right"]].set_visible(False)

    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  ✓ Dashboard saved → {output_path}")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGraphVisualization:
    # ── FK graph ──────────────────────────────────────────────────────────────

    def test_fk_graph_airline_saved(self, airline_schema, airline_profiles):
        """Build and save an annotated FK graph for the airline schema."""
        out = ARTIFACTS / "fk_graph_airline.png"
        _draw_fk_graph(
            airline_schema, airline_profiles, out,
            title="Airline Reservation — FK Directed Graph",
        )
        assert out.exists() and out.stat().st_size > 0

    def test_fk_graph_ecommerce_saved(self, ecommerce_schema, ecommerce_profiles):
        """Build and save an annotated FK graph for the e-commerce schema."""
        out = ARTIFACTS / "fk_graph_ecommerce.png"
        _draw_fk_graph(
            ecommerce_schema, ecommerce_profiles, out,
            title="E-Commerce — FK Directed Graph",
        )
        assert out.exists() and out.stat().st_size > 0

    # ── Score bar chart ───────────────────────────────────────────────────────

    def test_score_ranking_chart_saved(self, airline_schema, airline_profiles):
        """Save horizontal bar chart of composite scores for the airline schema."""
        out = ARTIFACTS / "score_ranking.png"
        _draw_score_bar_chart(
            airline_schema, airline_profiles, out,
            title="Airline — Table Importance Scores",
        )
        assert out.exists() and out.stat().st_size > 0

    # ── Dashboard ─────────────────────────────────────────────────────────────

    def test_dashboard_airline_saved(self, airline_schema, airline_profiles):
        """Save a 3-panel dashboard (graph + scores + centrality) for airline."""
        out = ARTIFACTS / "dashboard_airline.png"
        _draw_dashboard(
            airline_schema, airline_profiles, out,
            title="Airline Schema Dashboard",
        )
        assert out.exists() and out.stat().st_size > 0

    def test_dashboard_ecommerce_saved(self, ecommerce_schema, ecommerce_profiles):
        """Save a 3-panel dashboard for the e-commerce schema."""
        out = ARTIFACTS / "dashboard_ecommerce.png"
        _draw_dashboard(
            ecommerce_schema, ecommerce_profiles, out,
            title="E-Commerce Schema Dashboard",
        )
        assert out.exists() and out.stat().st_size > 0

    # ── Sanity checks embedded in visualization ───────────────────────────────

    def test_graph_node_count_matches_schema(self, airline_schema, airline_profiles):
        """The rendered graph should contain exactly as many nodes as tables."""
        svc = SchemaGraphService()
        G = svc.build_graph(airline_schema)
        assert G.number_of_nodes() == len(airline_schema.tables)

    def test_score_map_keys_match_schema_tables(self, airline_schema, airline_profiles):
        """score_tables returns exactly one entry per table in the schema."""
        svc = SchemaGraphService()
        G = svc.build_graph(airline_schema)
        scored = svc.score_tables(airline_schema, airline_profiles, G,
                                  top_n=len(airline_schema.tables))
        assert {s.table_name for s in scored} == set(airline_schema.table_names)

    def test_centrality_all_positive(self, airline_schema, airline_profiles):
        """PageRank scores must all be > 0 for a connected graph."""
        svc = SchemaGraphService()
        G = svc.build_graph(airline_schema)
        centrality = svc.compute_centrality(G)
        assert all(v > 0 for v in centrality.values())

