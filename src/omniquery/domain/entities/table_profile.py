from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TableProfile:
    """
    Statistical snapshot of a single table obtained during the profiling phase.

    Attributes:
        table_name:    Name of the profiled table.
        row_count:     Total number of rows (exact or estimated).
        null_counts:   Mapping column_name → number of NULL values.
        cardinality:   Mapping column_name → number of distinct values.
        sample_rows:   First N rows as list-of-dicts (for LLM context).
        numeric_stats: Per-column statistics (min, max, avg) for numeric cols.
        has_dates:     True if at least one column holds date/timestamp values.
        has_metrics:   True if at least one non-id numeric column exists.
    """

    table_name: str
    row_count: int = 0
    null_counts: dict[str, int] = field(default_factory=dict)
    cardinality: dict[str, int] = field(default_factory=dict)
    sample_rows: list[dict[str, Any]] = field(default_factory=list)
    numeric_stats: dict[str, dict[str, float]] = field(default_factory=dict)
    has_dates: bool = False
    has_metrics: bool = False

    # ------------------------------------------------------------------
    # Derived helpers
    # ------------------------------------------------------------------

    @property
    def null_ratio(self) -> float:
        """Average NULL ratio across all profiled columns (0.0 – 1.0)."""
        if not self.null_counts or self.row_count == 0:
            return 0.0
        ratios = [v / self.row_count for v in self.null_counts.values()]
        return sum(ratios) / len(ratios)

    @property
    def avg_cardinality(self) -> float:
        """Average cardinality across all profiled columns."""
        if not self.cardinality:
            return 0.0
        return sum(self.cardinality.values()) / len(self.cardinality)

    def summary_line(self) -> str:
        """One-line human-readable summary for CLI display."""
        flags = []
        if self.has_dates:
            flags.append("📅 dates")
        if self.has_metrics:
            flags.append("📊 metrics")
        flag_str = "  " + " · ".join(flags) if flags else ""
        return (
            f"{self.table_name}: {self.row_count:,} rows"
            f"  nulls={self.null_ratio:.1%}"
            f"  avg_card={self.avg_cardinality:.0f}"
            f"{flag_str}"
        )
