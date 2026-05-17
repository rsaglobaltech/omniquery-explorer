from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import text

from omniquery.domain.entities.table_profile import TableProfile
from omniquery.domain.ports.outbound.profiling_port import ProfilingPort
from omniquery.infrastructure.db.engine_pool import AsyncEnginePool, get_default_pool

logger = logging.getLogger(__name__)

# Column types that indicate a date/timestamp dimension. Used to set the
# `has_dates` flag on the profile so the ranker can prioritise tables
# that support time-series questions.
_DATE_TYPES = re.compile(
    r"date|time|timestamp|datetime|interval", re.IGNORECASE
)

# Column types that suggest numeric metrics. We exclude id-like names so
# a `customer_id INT` does not falsely flag the table as containing
# measurable quantities.
_NUMERIC_TYPES = re.compile(
    r"int|float|double|numeric|decimal|real|bigint|smallint|money|number",
    re.IGNORECASE,
)
_ID_NAMES = re.compile(r"^(id|uuid|pk|oid|rowid|_id)$", re.IGNORECASE)


def _quote(connection_url: str, identifier: str) -> str:
    """Return ``identifier`` quoted using the dialect's identifier quoting.

    Picking quoting purely from the URL avoids carrying an engine type
    down through the profiler API. MySQL/MariaDB use backticks; every
    other engine we support uses ANSI double quotes.
    """
    url = connection_url.lower()
    if "mysql" in url or "mariadb" in url:
        # Escape stray backticks to defend against malformed metadata.
        return "`" + identifier.replace("`", "``") + "`"
    return '"' + identifier.replace('"', '""') + '"'


def _supports_information_schema(connection_url: str) -> bool:
    """Oracle exposes ``ALL_TAB_COLUMNS`` instead of ANSI ``information_schema``."""
    url = connection_url.lower()
    return "oracle" not in url


class SqlProfilingAdapter(ProfilingPort):
    """
    Concrete profiling adapter that issues lightweight SQL queries.

    Borrows engines from the shared pool instead of creating one per
    call, and quotes identifiers per dialect to avoid the "double quote
    on MySQL" bug.
    """

    _TIMEOUT = 15  # seconds per query (advisory; tuned via engine pool)

    def __init__(self, pool: AsyncEnginePool | None = None) -> None:
        # Shared pool means every table profiled against the same URL
        # reuses the same warm connections.
        self._pool = pool or get_default_pool()

    async def profile_table(
        self,
        connection_url: str,
        table_name: str,
        sample_size: int = 5,
    ) -> TableProfile:
        engine = await self._pool.get(connection_url)
        tbl = _quote(connection_url, table_name)

        async with engine.connect() as conn:
            # ── Row count ────────────────────────────────────────────
            row_count = await self._row_count(conn, tbl, table_name)

            # ── Column metadata from DB ──────────────────────────────
            col_info = await self._column_info(conn, table_name, connection_url)

            null_counts: dict[str, int] = {}
            cardinality: dict[str, int] = {}
            numeric_stats: dict[str, dict[str, float]] = {}
            has_dates = False
            has_metrics = False

            for col_name, col_type in col_info.items():
                col = _quote(connection_url, col_name)

                # Null count — bounded by the engine's statement_timeout.
                try:
                    r = await conn.execute(
                        text(f"SELECT COUNT(*) FROM {tbl} WHERE {col} IS NULL")
                    )
                    null_counts[col_name] = r.scalar() or 0
                except Exception:
                    null_counts[col_name] = 0

                # COUNT DISTINCT is expensive — skip on huge tables.
                if row_count < 500_000:
                    try:
                        r = await conn.execute(
                            text(f"SELECT COUNT(DISTINCT {col}) FROM {tbl}")
                        )
                        cardinality[col_name] = r.scalar() or 0
                    except Exception:
                        cardinality[col_name] = 0

                if _DATE_TYPES.search(col_type):
                    has_dates = True

                if _NUMERIC_TYPES.search(col_type) and not _ID_NAMES.match(col_name):
                    has_metrics = True
                    # MIN/MAX/AVG. We avoid the Postgres ``::numeric`` cast
                    # since the column is already numeric and the cast
                    # breaks on MySQL/Oracle/SQLite.
                    try:
                        r = await conn.execute(
                            text(
                                f"SELECT MIN({col}), MAX({col}), AVG({col}) FROM {tbl}"
                            )
                        )
                        row = r.fetchone()
                        if row:
                            numeric_stats[col_name] = {
                                "min": float(row[0]) if row[0] is not None else 0.0,
                                "max": float(row[1]) if row[1] is not None else 0.0,
                                "avg": float(row[2]) if row[2] is not None else 0.0,
                            }
                    except Exception:
                        pass

            # ── Sample rows ──────────────────────────────────────────
            sample_rows: list[dict[str, Any]] = []
            try:
                r = await conn.execute(text(f"SELECT * FROM {tbl} LIMIT {sample_size}"))
                keys = list(r.keys())
                sample_rows = [dict(zip(keys, row, strict=False)) for row in r.fetchall()]
                # Truncate long values so they do not blow up LLM prompts.
                sample_rows = [
                    {
                        k: (str(v)[:80] + "…" if isinstance(v, str) and len(str(v)) > 80 else v)
                        for k, v in row.items()
                    }
                    for row in sample_rows
                ]
            except Exception:
                pass

            return TableProfile(
                table_name=table_name,
                row_count=row_count,
                null_counts=null_counts,
                cardinality=cardinality,
                sample_rows=sample_rows,
                numeric_stats=numeric_stats,
                has_dates=has_dates,
                has_metrics=has_metrics,
            )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _row_count(self, conn: Any, quoted_table: str, raw_name: str) -> int:
        try:
            r = await conn.execute(text(f"SELECT COUNT(*) FROM {quoted_table}"))
            return r.scalar() or 0
        except Exception as exc:
            logger.warning("row_count failed for %s: %s", raw_name, exc)
            return 0

    async def _column_info(
        self, conn: Any, table_name: str, connection_url: str
    ) -> dict[str, str]:
        """Return ``{col_name: data_type}`` for the given table."""
        # Oracle keeps catalog data in ALL_TAB_COLUMNS rather than the
        # ANSI information_schema, so route accordingly.
        if not _supports_information_schema(connection_url):
            try:
                r = await conn.execute(
                    text(
                        "SELECT column_name, data_type "
                        "FROM all_tab_columns "
                        "WHERE LOWER(table_name) = LOWER(:tn) "
                        "ORDER BY column_id"
                    ),
                    {"tn": table_name},
                )
                return {row[0]: row[1] for row in r.fetchall()}
            except Exception as exc:
                logger.warning("column_info(oracle) failed for %s: %s", table_name, exc)
                return {}

        try:
            r = await conn.execute(
                text(
                    "SELECT column_name, data_type "
                    "FROM information_schema.columns "
                    "WHERE LOWER(table_name) = LOWER(:tn) "
                    "ORDER BY ordinal_position"
                ),
                {"tn": table_name},
            )
            return {row[0]: row[1] for row in r.fetchall()}
        except Exception as exc:
            logger.warning("column_info failed for %s: %s", table_name, exc)
            return {}
