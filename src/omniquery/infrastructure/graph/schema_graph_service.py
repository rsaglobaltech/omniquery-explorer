from __future__ import annotations

import logging

import networkx as nx

from omniquery.domain.entities.database_schema import DatabaseSchema
from omniquery.domain.entities.scored_table import ScoredTable
from omniquery.domain.entities.table_profile import TableProfile

logger = logging.getLogger(__name__)


class SchemaGraphService:
    """
    Domain service that builds a directed FK graph from a DatabaseSchema
    and computes importance metrics for each table.

    The graph models tables as nodes and foreign-key relationships as
    directed edges (child → parent).  PageRank and in-degree are used
    as proxies for "how central / referenced a table is".
    """

    def build_graph(self, schema: DatabaseSchema) -> nx.DiGraph:
        """
        Build a DiGraph from FK relationships.

        Nodes carry attributes: row_count (populated later), has_dates, has_metrics.
        Edges carry attribute: fk_col (the column that holds the FK).
        """
        G = nx.DiGraph()

        for table in schema.tables:
            G.add_node(table.name)
            for col in table.foreign_keys:
                if col.foreign_key:
                    ref_table = col.foreign_key.referred_table
                    G.add_node(ref_table)
                    # Edge: child table → parent/referenced table
                    G.add_edge(table.name, ref_table, fk_col=col.name)

        return G

    def compute_centrality(self, graph: nx.DiGraph) -> dict[str, float]:
        """
        Return PageRank scores for every node in the graph.

        ## Algorithm: PageRank  (Brin & Page, 1998)
        Originally designed to rank web pages by link importance, it works
        equally well on any directed graph.  The iterative formula is:

            PR(u) = (1 - α) / N  +  α * Σ_{v → u}  PR(v) / out_degree(v)

        where:
          - PR(u)          : PageRank score of node u  (our table)
          - N              : total number of nodes in the graph
          - α (alpha=0.85) : *damping factor* — probability of following an
                             edge rather than jumping to a random node.
                             0.85 is the canonical value from the original paper.
          - Σ_{v → u}      : sum over all nodes v that have a directed edge
                             to u (i.e. tables whose FK points to table u).
          - out_degree(v)  : number of outgoing edges from v (how many FKs
                             that child table declares).

        Intuition in our schema graph (child → parent edges):
          A parent/dimension table referenced by many child tables accumulates
          PageRank from each of them.  A child that is itself referenced by
          others also passes score up.  The result is a normalised [0, 1]
          importance score per table.

        Reference: S. Brin & L. Page, "The Anatomy of a Large-Scale
        Hypertextual Web Search Engine", WWW 1998.
        NetworkX implementation: nx.pagerank(G, alpha)

        Fallback: if PageRank fails (e.g. disconnected graph / convergence
        issues) we use *normalised in-degree* — simply the fraction of all
        incoming FK edges that land on each table.  Simpler but equivalent
        for non-iterative scenarios.
        """
        if graph.number_of_nodes() == 0:
            return {}
        try:
            return nx.pagerank(graph, alpha=0.85)
        except Exception as exc:
            logger.warning("PageRank failed, falling back to in_degree: %s", exc)
            in_deg = dict(graph.in_degree())
            total = sum(in_deg.values()) or 1
            return {n: v / total for n, v in in_deg.items()}

    def score_tables(
        self,
        schema: DatabaseSchema,
        profiles: dict[str, TableProfile],
        graph: nx.DiGraph,
        top_n: int = 15,
    ) -> list[ScoredTable]:
        """
        Produce a ranked list of the most important tables for EDA.

        ## Scoring formula
        A hand-crafted *weighted linear combination* of six normalised factors,
        each in [0, 1].  The idea follows standard feature-weighting practice
        in information-retrieval ranking (similar to BM25-style field boosting)
        but simplified to a transparent additive model so weights can be tuned
        intuitively.

            score = 0.30 * f_rows        # volume: bigger tables carry more signal
                  + 0.25 * f_central     # graph: tables many FKs point to are core
                  + 0.15 * f_semantic    # name heuristic: known domain concepts
                  + 0.15 * f_metrics     # numeric cols → analysable / KPI table
                  + 0.10 * f_quality     # low null ratio → reliable data
                  + 0.05 * f_dates       # temporal cols → trend analysis possible

        Factor details:
          f_rows     = row_count / max_row_count   (linear normalisation)
          f_central  = PageRank score from compute_centrality()  (already in [0,1])
          f_semantic = 1.0 if table name contains a known core concept, else 0.0
          f_metrics  = 1.0 if the table has at least one numeric column, else 0.0
          f_quality  = 1.0 - null_ratio            (higher quality → higher score)
          f_dates    = 1.0 if the table has at least one date/time column, else 0.0

        Weights rationale:
          - Row count and centrality share the highest weight (0.30 / 0.25)
            because in practice the largest, most-referenced tables are almost
            always the most interesting for EDA.
          - Semantic and metrics bonuses (0.15 each) break ties in favour of
            tables whose names or contents suggest analytical value.
          - Quality and dates are smaller bonuses that nudge the ranking without
            dominating it.

        The weights sum to 1.0, so scores are interpretable as a percentage of
        the theoretical maximum.
        """
        centrality = self.compute_centrality(graph)

        # Normalise row counts to [0, 1]
        row_counts = {
            t: profiles[t].row_count if t in profiles else 0
            for t in schema.table_names
        }
        max_rows = max(row_counts.values(), default=1) or 1

        scored: list[ScoredTable] = []
        for table in schema.tables:
            name = table.name
            reasons: list[str] = []

            # ── Factor 1: row count ──────────────────────────────────────
            rc = row_counts.get(name, 0)
            f_rows = rc / max_rows
            if rc > 0:
                reasons.append(f"{rc:,} rows")

            # ── Factor 2: graph centrality ───────────────────────────────
            f_central = centrality.get(name, 0.0)
            if f_central > 0.05:
                reasons.append(f"centrality={f_central:.3f}")

            # ── Factor 3: semantic score of table name ───────────────────
            f_semantic = _semantic_score(name)
            if f_semantic > 0:
                reasons.append("meaningful name")

            # ── Factor 4: has numeric metrics ───────────────────────────
            profile = profiles.get(name)
            f_metrics = 1.0 if (profile and profile.has_metrics) else 0.0
            if profile and profile.has_metrics:
                reasons.append("has metrics")

            # ── Factor 5: data quality (low nulls) ───────────────────────
            f_quality = 1.0 - (profile.null_ratio if profile else 0.5)

            # ── Factor 6: has date columns ───────────────────────────────
            f_dates = 1.0 if (profile and profile.has_dates) else 0.0
            if profile and profile.has_dates:
                reasons.append("has dates")

            score = (
                0.30 * f_rows
                + 0.25 * f_central
                + 0.15 * f_semantic
                + 0.15 * f_metrics
                + 0.10 * f_quality
                + 0.05 * f_dates
            )

            scored.append(
                ScoredTable(
                    table_name=name,
                    score=round(score, 4),
                    reasons=reasons,
                    centrality=round(f_central, 4),
                    row_count=rc,
                )
            )

        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:top_n]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CORE_WORDS = {
    # generic entities
    "user", "users", "account", "accounts", "customer", "customers",
    "order", "orders", "product", "products", "transaction", "transactions",
    "event", "events", "session", "sessions", "log", "logs",
    # bioinformatics / omniquery domain
    "rna", "sequence", "sequences", "taxonomy", "xref", "accession",
    "assembly", "genome", "gene", "protein", "feature", "annotation",
    "literature", "publication", "author", "database",
}


def _semantic_score(table_name: str) -> float:
    """
    Heuristic: 1.0 if the name contains a known core concept, else 0.0.

    Partition/staging tables are penalised.
    """
    name_lower = table_name.lower()
    # Penalise partition/staging/temp tables
    if any(name_lower.startswith(p) for p in ("xref_p", "tmp_", "temp_", "stg_", "bak_")):
        return 0.0
    for word in _CORE_WORDS:
        if word in name_lower:
            return 1.0
    return 0.0
