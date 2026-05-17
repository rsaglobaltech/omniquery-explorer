from __future__ import annotations

import logging
import time

from sqlalchemy.exc import OperationalError, ProgrammingError

from omniquery.domain.entities.analysis_result import AnalysisResult
from omniquery.domain.entities.eda_query import EdaQuery
from omniquery.domain.ports.inbound.eda_use_case import EdaUseCase
from omniquery.domain.ports.outbound.database_port import DatabasePort
from omniquery.domain.ports.outbound.llm_port import LlmPort
from omniquery.infrastructure.cache.semantic_cache import SemanticQueryCache
from omniquery.infrastructure.db.sql_guard import SqlGuardError
from omniquery.infrastructure.governance.cost_guard import BudgetExceeded, BudgetTracker
from omniquery.infrastructure.governance.pii_policy import PiiPolicy
from omniquery.infrastructure.persistence.session_store import PersistenceStore

logger = logging.getLogger(__name__)

_MAX_SQL_RETRIES = 2  # max attempts to fix a SQL error via LLM feedback


class RunEdaUseCase(EdaUseCase):
    """
    Concrete orchestration of the EDA pipeline.

    Receives its dependencies (DatabasePort, LlmPort, PersistenceStore)
    through constructor injection — no infrastructure import lives here
    except for the optional persistence hook.

    SQL retry loop:
        When the DB returns a ProgrammingError or OperationalError the use-case
        feeds the error message back to the LLM (via LlmPort.fix_sql) and retries
        execution up to _MAX_SQL_RETRIES times before surfacing the error.
    """

    def __init__(
        self,
        db: DatabasePort,
        llm: LlmPort,
        store: PersistenceStore | None = None,
        budget: BudgetTracker | None = None,
        pii: PiiPolicy | None = None,
        semantic_cache: SemanticQueryCache | None = None,
    ) -> None:
        self._db = db
        self._llm = llm
        self._store = store
        # Optional in-process budget tracker — caps per-session usage.
        # The use-case bumps the query counter at the start so even
        # failed runs count against the quota (prevents retry abuse).
        self._budget = budget
        # PII policy: when present, removes sensitive columns from the
        # schema before showing it to the LLM and masks them in any
        # rows we return upstream.
        self._pii = pii
        # Semantic cache (off by default). On a hit we skip the LLM
        # generate_sql call and execute the cached statement directly;
        # the result is still routed through the full safety stack
        # (sql_guard, statement_timeout, cost_guard) inside the DB
        # adapter so a cached SQL is no less safe than a fresh one.
        self._semantic_cache = semantic_cache

    async def run_eda(self, query: EdaQuery) -> AnalysisResult:
        result = AnalysisResult(question=query.question)
        sql: str = ""
        status: str = "pending"
        started = time.perf_counter()
        session_id = ""

        try:
            # Enforce per-session budget early. Use connection_url as the
            # bucket key when no explicit session ID is provided. If the
            # budget is exhausted, fail fast before doing any DB or LLM work.
            if self._budget is not None:
                try:
                    self._budget.register_query(query.connection_url)
                except BudgetExceeded as bx:
                    result.error = str(bx)
                    return result

            # Step 1 — Introspect schema
            logger.info("Introspecting schema for: %s", query.connection_url)
            schema = await self._db.get_schema(query.connection_url)
            # Strip denylisted columns BEFORE the LLM sees the schema.
            # We keep the raw schema for ourselves (e.g. for the persistence
            # layer) and only pass the redacted view to generate_sql /
            # fix_sql / generate_report.
            llm_schema = self._pii.redact_schema(schema) if self._pii else schema

            if self._store is not None:
                session_id = await self._store.start_session(
                    query.connection_url, schema.engine.value
                )

            # Step 2 — Generate SQL. We consult the semantic cache
            # FIRST: if a near-duplicate question (cosine >= threshold,
            # same DB fingerprint) is on file, reuse its SQL and skip
            # the LLM round-trip entirely. We still go through the
            # normal execute/report path so the user gets fresh rows
            # and a fresh narrative on top of the cached SQL.
            sql = ""
            cached_hit = None
            if self._semantic_cache is not None and self._semantic_cache.enabled:
                cached_hit = await self._semantic_cache.lookup(
                    query.question, query.connection_url
                )
            if cached_hit is not None:
                sql = cached_hit.generated_sql
                logger.info("semantic_cache: reusing SQL from cache")
            else:
                logger.info("Generating SQL for question: %s", query.question)
                sql = await self._llm.generate_sql(llm_schema, query)
            result.generated_sql = sql

            # Step 3 — Execute SQL with retry-on-error loop
            rows: list = []
            last_error: str = ""
            for attempt in range(1 + _MAX_SQL_RETRIES):
                try:
                    logger.info(
                        "Executing SQL (attempt %d/%d): %s",
                        attempt + 1,
                        1 + _MAX_SQL_RETRIES,
                        sql,
                    )
                    rows = await self._db.execute_query(
                        query.connection_url, sql, query.max_rows
                    )
                    last_error = ""
                    break

                except SqlGuardError as guard_err:
                    # LLM emitted malformed or unsafe SQL: sql_guard
                    # refused it before it ever touched the database.
                    # Feed the parser's error back through fix_sql so the
                    # model can self-correct rather than fail the run.
                    last_error = str(guard_err)
                    logger.warning(
                        "SQL attempt %d rejected by guard: %s",
                        attempt + 1,
                        last_error,
                    )
                    if attempt < _MAX_SQL_RETRIES:
                        sql = await self._llm.fix_sql(
                            llm_schema, query, sql, last_error
                        )
                        result.generated_sql = sql
                        continue
                    raise
                except (ProgrammingError, OperationalError) as db_err:
                    last_error = str(db_err.orig) if db_err.orig else str(db_err)
                    logger.warning(
                        "SQL attempt %d failed: %s", attempt + 1, last_error
                    )
                    if attempt < _MAX_SQL_RETRIES:
                        logger.info("Asking LLM to fix the SQL…")
                        # Use the redacted schema again — the LLM must not
                        # see PII columns even during fix attempts.
                        sql = await self._llm.fix_sql(
                            llm_schema, query, sql, last_error
                        )
                        result.generated_sql = sql
                    else:
                        raise

            # Mask any sensitive values BEFORE they are exposed in the
            # report prompt or returned to the caller. Note we mask the
            # in-memory list once and then both reuse paths read masked.
            if self._pii is not None:
                rows = self._pii.mask_rows(rows)
            result.raw_data = rows

            # Step 4 — Generate EDA report (masked rows + redacted schema)
            logger.info("Generating EDA report (%d rows).", len(rows))
            report = await self._llm.generate_report(llm_schema, query, rows)
            result.report = report
            status = "ok"

            # Step 5 — Cache the successful (question, SQL) pair. We
            # only store on cache MISS so the embedder isn't called for
            # paraphrases that already hit; ``store`` is itself a no-op
            # when the cache is disabled.
            if (
                self._semantic_cache is not None
                and self._semantic_cache.enabled
                and cached_hit is None
            ):
                try:
                    await self._semantic_cache.store(
                        query.question,
                        result.generated_sql or "",
                        query.connection_url,
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("Failed to write semantic cache entry")

        except Exception as exc:
            logger.error("EDA pipeline failed: %s", exc, exc_info=True)
            result.error = str(exc)
            status = "error"

        finally:
            if self._store is not None and session_id:
                duration_ms = int((time.perf_counter() - started) * 1000)
                try:
                    await self._store.record_query(
                        session_id=session_id,
                        query=query,
                        generated_sql=result.generated_sql or sql,
                        status=status,
                        error=result.error,
                        row_count=result.row_count,
                        duration_ms=duration_ms,
                        report_markdown=result.report or "",
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("Failed to persist query record")

        return result
