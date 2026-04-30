"""
Terminal-friendly chart helpers using matplotlib.
Charts are saved as PNG to a temp file and opened with the OS viewer.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")  # non-interactive backend — no display required
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker


_PALETTE = [
    "#4C8BF5", "#34A853", "#FBBC04", "#EA4335",
    "#7B61FF", "#00BCD4", "#FF6D00", "#8D6E63",
]


def _open_file(path: str) -> None:
    """Open a file with the default OS application (macOS / Linux)."""
    subprocess.Popen(["open" if _is_macos() else "xdg-open", path])


def _is_macos() -> bool:
    import platform
    return platform.system() == "Darwin"


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def chart_query_results(
    rows: list[dict[str, Any]],
    title: str = "Resultados de la consulta",
) -> str | None:
    """
    Auto-detect the best chart type from query rows and open it.
    Returns the path to the saved PNG, or None if no chart could be made.
    """
    if not rows:
        return None

    cols = list(rows[0].keys())

    # Find label column (first non-numeric) and value column (first numeric)
    label_col: str | None = None
    value_cols: list[str] = []
    for col in cols:
        sample = [r[col] for r in rows if r[col] is not None][:5]
        if all(_is_numeric(v) for v in sample):
            value_cols.append(col)
        elif label_col is None:
            label_col = col

    if not value_cols:
        return None

    labels = [str(r.get(label_col) if label_col else i) for i, r in enumerate(rows)]
    values = [_to_float(r.get(value_cols[0], 0)) for r in rows]

    # Truncate to 20 items for readability
    if len(labels) > 20:
        labels, values = labels[:20], values[:20]

    fig, ax = plt.subplots(figsize=(max(8, len(labels) * 0.55), 5))
    fig.patch.set_facecolor("#1E1E2E")
    ax.set_facecolor("#1E1E2E")

    if len(labels) <= 2:
        # Pie chart for 2 or fewer categories
        wedge_colors = _PALETTE[: len(labels)]
        ax.pie(
            values,
            labels=labels,
            colors=wedge_colors,
            autopct="%1.1f%%",
            textprops={"color": "white"},
        )
    else:
        bars = ax.bar(range(len(labels)), values, color=_PALETTE[0], edgecolor="#333355")
        for bar, val in zip(bars, values):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + max(values) * 0.01,
                _fmt_value(val),
                ha="center",
                va="bottom",
                fontsize=8,
                color="white",
            )
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=40, ha="right", fontsize=9, color="white")
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: _fmt_value(x)))
        for spine in ax.spines.values():
            spine.set_edgecolor("#444466")
        ax.tick_params(colors="white")
        ax.yaxis.label.set_color("white")

    ax.set_title(title, color="white", fontsize=12, pad=12)
    fig.tight_layout()

    path = _save_and_open(fig, "omniquery_explore")
    plt.close(fig)
    return path


def chart_profile_scores(
    scored_tables: list[Any],
    top_n: int = 15,
    title: str = "Importancia de tablas",
) -> str | None:
    """Bar chart of ScoredTable importance scores."""
    items = scored_tables[:top_n]
    if not items:
        return None

    names = [s.table_name for s in items]
    scores = [s.score for s in items]
    rows_norm = _normalize([s.row_count for s in items])

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, max(4, len(names) * 0.45)))
    fig.patch.set_facecolor("#1E1E2E")

    for ax in (ax1, ax2):
        ax.set_facecolor("#1E1E2E")
        for spine in ax.spines.values():
            spine.set_edgecolor("#444466")
        ax.tick_params(colors="white")

    # Left: importance scores
    ax1.barh(names[::-1], scores[::-1], color=_PALETTE[0])
    ax1.set_xlabel("Score de importancia", color="white")
    ax1.set_title("Score compuesto", color="white")
    ax1.xaxis.label.set_color("white")
    ax1.set_xlim(0, 1)
    for i, (v, n) in enumerate(zip(scores[::-1], names[::-1])):
        ax1.text(v + 0.01, i, f"{v:.3f}", va="center", fontsize=8, color="white")

    # Right: row count (normalised)
    ax2.barh(names[::-1], rows_norm[::-1], color=_PALETTE[1])
    ax2.set_xlabel("Filas (normalizado)", color="white")
    ax2.set_title("Volumen de datos", color="white")
    ax2.xaxis.label.set_color("white")
    ax2.set_xlim(0, 1.1)
    for i, (v, s) in enumerate(zip(rows_norm[::-1], items[::-1])):
        ax2.text(v + 0.01, i, f"{s.row_count:,}", va="center", fontsize=7, color="white")

    fig.suptitle(title, color="white", fontsize=13, y=1.01)
    ax1.yaxis.set_tick_params(labelsize=8, labelcolor="white")
    ax2.yaxis.set_tick_params(labelsize=8, labelcolor="white")
    fig.tight_layout()

    path = _save_and_open(fig, "omniquery_profile")
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _save_and_open(fig: plt.Figure, prefix: str) -> str:
    tmp = tempfile.NamedTemporaryFile(
        suffix=".png", prefix=f"{prefix}_", delete=False
    )
    fig.savefig(tmp.name, dpi=130, bbox_inches="tight", facecolor=fig.get_facecolor())
    tmp.close()
    _open_file(tmp.name)
    return tmp.name


def _is_numeric(v: Any) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def _to_float(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _fmt_value(v: float) -> str:
    if abs(v) >= 1_000_000:
        return f"{v/1_000_000:.1f}M"
    if abs(v) >= 1_000:
        return f"{v/1_000:.1f}K"
    if v == int(v):
        return str(int(v))
    return f"{v:.2f}"


def _normalize(values: list[float]) -> list[float]:
    mx = max(values) if values else 1
    return [v / mx if mx else 0 for v in values]
