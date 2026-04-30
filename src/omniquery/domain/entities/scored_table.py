from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ScoredTable:
    """
    A table together with its importance score computed by the scoring service.

    Attributes:
        table_name:  Name of the table.
        score:       Composite importance score in [0.0, 1.0].
        reasons:     Human-readable list of factors that contributed to the score.
        centrality:  PageRank / betweenness centrality in the FK graph.
        row_count:   Row count from profiling (0 if profiling was skipped).
    """

    table_name: str
    score: float
    reasons: list[str] = field(default_factory=list)
    centrality: float = 0.0
    row_count: int = 0

    def __lt__(self, other: ScoredTable) -> bool:  # enables sorted()
        return self.score < other.score
