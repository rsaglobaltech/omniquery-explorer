"""Cost-guard: protects the analysed DB and the LLM budget.

Two layers of control:

1. **EXPLAIN gate** — before executing a SELECT we ask the engine to
   explain it (Postgres ``EXPLAIN (FORMAT JSON)`` or MySQL
   ``EXPLAIN FORMAT=JSON``) and reject the query if either the
   total cost or the estimated row count exceeds the configured
   thresholds. This stops the LLM from accidentally launching a
   full-table scan of a 200M-row fact table.

2. **In-process budget** — counts queries and LLM tokens per session.
   Once a session exceeds its cap, ``BudgetExceeded`` is raised. The
   budget resets when the process restarts; production deployments
   should persist counters in the persistence DB (see IMPROVEMENTS.md).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from omniquery.config import CostGuardSettings
from omniquery.domain.entities.database_schema import EngineType

logger = logging.getLogger(__name__)


class CostGuardError(RuntimeError):
    """Raised when the EXPLAIN gate rejects a query."""


class BudgetExceeded(RuntimeError):
    """Raised when a session exceeds its query/token cap."""


@dataclass
class _Counters:
    """Per-session running totals tracked in memory."""

    queries: int = 0
    tokens: int = 0


@dataclass
class BudgetTracker:
    """Tracks query and token usage per session ID.

    Thread-safety: not enforced — calls are awaited from a single event
    loop. If you ever fan out across loops, wrap counters with a lock.
    """

    settings: CostGuardSettings
    _per_session: dict[str, _Counters] = field(default_factory=dict)

    def _bucket(self, session_id: str) -> _Counters:
        # Lazily allocate per-session counter dict; "" is the anonymous bucket
        # so CLI invocations without explicit sessions still get accounted.
        return self._per_session.setdefault(session_id or "_anon", _Counters())

    def register_query(self, session_id: str) -> None:
        """Increment query count; raise BudgetExceeded if over the cap."""
        b = self._bucket(session_id)
        b.queries += 1
        if b.queries > self.settings.max_queries_per_session:
            raise BudgetExceeded(
                f"Session {session_id!r} exceeded max_queries_per_session"
                f" ({self.settings.max_queries_per_session})."
            )

    def register_tokens(self, session_id: str, tokens: int) -> None:
        """Accumulate LLM tokens; raise BudgetExceeded if over the cap."""
        if tokens <= 0:
            return
        b = self._bucket(session_id)
        b.tokens += tokens
        if b.tokens > self.settings.max_tokens_per_session:
            raise BudgetExceeded(
                f"Session {session_id!r} exceeded max_tokens_per_session"
                f" ({self.settings.max_tokens_per_session})."
            )

    def snapshot(self, session_id: str) -> dict[str, int]:
        """Return current counters for the session (for /health endpoints)."""
        b = self._bucket(session_id)
        return {"queries": b.queries, "tokens": b.tokens}


async def explain_and_check(
    conn: AsyncConnection,
    engine_type: EngineType,
    sql: str,
    settings: CostGuardSettings,
) -> None:
    """Run EXPLAIN and reject the query if it crosses the thresholds.

    Silently no-ops when:
    - the guard is disabled in settings,
    - the engine does not support a portable cost JSON output (Oracle).

    EXPLAIN itself does not execute the query — it asks the planner for
    an estimated plan. Costs are engine-specific units (Postgres uses
    arbitrary planner units; MySQL uses query cost units).
    """
    if not settings.explain_enabled:
        return

    if engine_type == EngineType.POSTGRESQL:
        # FORMAT JSON gives a structured root with "Plan" → "Total Cost"
        # and "Plan Rows" so we can compare without parsing free text.
        result = await conn.execute(text(f"EXPLAIN (FORMAT JSON) {sql}"))
        row = result.fetchone()
        if not row:
            return
        plan_doc = row[0]
        # asyncpg may return a Python list/dict already; psycopg returns str.
        if isinstance(plan_doc, str):
            plan_doc = json.loads(plan_doc)
        root = plan_doc[0]["Plan"] if isinstance(plan_doc, list) else plan_doc["Plan"]
        cost = float(root.get("Total Cost", 0.0))
        rows_est = int(root.get("Plan Rows", 0))
        _check_thresholds(cost, rows_est, settings)
        return

    if engine_type == EngineType.MYSQL:
        # MySQL returns a JSON document in a single TEXT column.
        result = await conn.execute(text(f"EXPLAIN FORMAT=JSON {sql}"))
        row = result.fetchone()
        if not row:
            return
        plan_doc = row[0]
        if isinstance(plan_doc, str):
            plan_doc = json.loads(plan_doc)
        # query_block.cost_info.query_cost is the top-level estimated cost.
        query_block = plan_doc.get("query_block", {})
        cost = float(query_block.get("cost_info", {}).get("query_cost", 0.0))
        rows_est = _mysql_estimated_rows(query_block)
        _check_thresholds(cost, rows_est, settings)
        return

    # Oracle: skip — no portable JSON plan output without DBMS_XPLAN.
    logger.debug("cost_guard: EXPLAIN gate skipped for engine %s", engine_type)


def _mysql_estimated_rows(node: dict) -> int:
    """Recursively pluck the largest 'rows_examined_per_scan' in a MySQL plan."""
    # Walking the tree finds the heaviest table access in the plan, which
    # is a reasonable proxy for "did the planner foresee a huge scan?".
    largest = 0
    if isinstance(node, dict):
        if "table" in node and isinstance(node["table"], dict):
            rows = node["table"].get("rows_examined_per_scan", 0)
            if isinstance(rows, int) and rows > largest:
                largest = rows
        for v in node.values():
            child = _mysql_estimated_rows(v) if isinstance(v, (dict, list)) else 0
            if child > largest:
                largest = child
    elif isinstance(node, list):
        for item in node:
            child = _mysql_estimated_rows(item)
            if child > largest:
                largest = child
    return largest


def _check_thresholds(
    cost: float, rows_est: int, settings: CostGuardSettings
) -> None:
    """Raise CostGuardError when either threshold is breached."""
    if cost > settings.max_plan_cost:
        raise CostGuardError(
            f"Query rejected: estimated plan cost {cost:.0f} exceeds limit "
            f"{settings.max_plan_cost:.0f}."
        )
    if rows_est > settings.max_plan_rows:
        raise CostGuardError(
            f"Query rejected: estimated rows {rows_est:,} exceed limit "
            f"{settings.max_plan_rows:,}."
        )
