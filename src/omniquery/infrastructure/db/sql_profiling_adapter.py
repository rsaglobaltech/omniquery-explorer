from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from omniquery.domain.entities.table_profile import TableProfile
from omniquery.domain.ports.outbound.profiling_port import ProfilingPort

logger = logging.getLogger(__name__)

# Column types that indicate a date/timestamp dimension
_DATE_TYPES = re.compile(
    r"date|time|timestamp|datetime|interval", re.IGNORECASE
)
# Column types that indicate numeric metrics (excluding pure ids)
_NUMERIC_TYPES = re.compile(
    r"int|float|double|numeric|decimal|real|bigint|smallint|money|number",
    re.IGNORECASE,
)
_ID_NAMES = re.compile(r"^(id|uuid|pk|oid|rowid|_id)$", re.IGNORECASE)


class SqlProfilingAdapter(ProfilingPort):
    """
    Concrete profiling adapter that issues lightweight SQL queries.

    Uses engine-specific syntax where available, falls back to ANSI SQL.
    Designed to be fast and read-only: no indexes are built, no temp
    tables are created.
    """

    _TIMEOUT = 15  # seconds per query

    async def profile_table(
        self,
        connection_url: str,
        table_name: str,
        sample_size: int = 5,
    ) -> TableProfile:
        engine = create_async_engine(connection_url, pool_pre_ping=True)
        try:
            async with engine.connect() as conn:
                # ── Row count ────────────────────────────────────────────
                row_count = await self._row_count(conn, table_name)

                # ── Column metadata from DB ──────────────────────────────
                col_info = await self._column_info(conn, table_name, connection_url)

                # ── Per-column null counts & cardinality ─────────────────
                null_counts: dict[str, int] = {}
                cardinality: dict[str, int] = {}
                numeric_stats: dict[str, dict[str, float]] = {}
                has_dates = False
                has_metrics = False

                for col_name, col_type in col_info.items():
                    # Null count
                    try:
                        r = await conn.execute(
                            text(
                                f'SELECT COUNT(*) FROM "{table_name}"'
                                f' WHERE "{col_name}" IS NULL'
                            )
                        )
                        null_counts[col_name] = r.scalar() or 0
                    except Exception:
                        null_counts[col_name] = 0

                    # Cardinality (capped to avoid slow COUNT DISTINCT on huge tables)
                    if row_count < 500_000:
                        try:
                            r = await conn.execute(
                                text(
                                    f'SELECT COUNT(DISTINCT "{col_name}")'
                                    f' FROM "{table_name}"'
                                )
                            )
                            cardinality[col_name] = r.scalar() or 0
                        except Exception:
                            cardinality[col_name] = 0

                    if _DATE_TYPES.search(col_type):
                        has_dates = True

                    if _NUMERIC_TYPES.search(col_type) and not _ID_NAMES.match(col_name):
                        has_metrics = True
                        try:
                            r = await conn.execute(
                                text(
                                    f'SELECT MIN("{col_name}"), MAX("{col_name}"),'
                                    f' AVG("{col_name}"::numeric)'
                                    f' FROM "{table_name}"'
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
                    r = await conn.execute(
                        text(f'SELECT * FROM "{table_name}" LIMIT {sample_size}')
                    )
                    keys = list(r.keys())
                    sample_rows = [dict(zip(keys, row)) for row in r.fetchall()]
                    # Truncate long values to avoid bloating LLM prompts
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
        finally:
            await engine.dispose()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _row_count(self, conn: Any, table_name: str) -> int:
        try:
            r = await conn.execute(text(f'SELECT COUNT(*) FROM "{table_name}"'))
            return r.scalar() or 0
        except Exception as exc:
            logger.warning("row_count failed for %s: %s", table_name, exc)
            return 0

    async def _column_info(
        self, conn: Any, table_name: str, connection_url: str
    ) -> dict[str, str]:
        """Return {col_name: data_type} from information_schema."""
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
