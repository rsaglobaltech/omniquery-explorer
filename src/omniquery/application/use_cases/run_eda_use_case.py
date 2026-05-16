from __future__ import annotations

import logging

from sqlalchemy.exc import OperationalError, ProgrammingError

from omniquery.domain.entities.analysis_result import AnalysisResult
from omniquery.domain.entities.eda_query import EdaQuery
from omniquery.domain.ports.inbound.eda_use_case import EdaUseCase
from omniquery.domain.ports.outbound.database_port import DatabasePort
from omniquery.domain.ports.outbound.llm_port import LlmPort

logger = logging.getLogger(__name__)

_MAX_SQL_RETRIES = 2  # max attempts to fix a SQL error via LLM feedback


class RunEdaUseCase(EdaUseCase):
    """
    Concrete orchestration of the EDA pipeline.

    Receives its dependencies (DatabasePort, LlmPort) through constructor
    injection — no infrastructure import lives here.

    SQL retry loop:
        When the DB returns a ProgrammingError or OperationalError the use-case
        feeds the error message back to the LLM (via LlmPort.fix_sql) and retries
        execution up to _MAX_SQL_RETRIES times before surfacing the error.
    """

    def __init__(self, db: DatabasePort, llm: LlmPort) -> None:
        self._db = db
        self._llm = llm

    async def run_eda(self, query: EdaQuery) -> AnalysisResult:
        result = AnalysisResult(question=query.question)

        try:
            # Step 1 — Introspect schema
            logger.info("Introspecting schema for: %s", query.connection_url)
            schema = await self._db.get_schema(query.connection_url)

            # Step 2 — Generate SQL
            logger.info("Generating SQL for question: %s", query.question)
            sql = await self._llm.generate_sql(schema, query)
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
                    break  # success

                except (ProgrammingError, OperationalError) as db_err:
                    last_error = str(db_err.orig) if db_err.orig else str(db_err)
                    logger.warning(
                        "SQL attempt %d failed: %s", attempt + 1, last_error
                    )
                    if attempt < _MAX_SQL_RETRIES:
                        logger.info("Asking LLM to fix the SQL…")
                        sql = await self._llm.fix_sql(
                            schema, query, sql, last_error
                        )
                        result.generated_sql = sql  # expose the fixed SQL
                    else:
                        raise  # exhausted retries — propagate to outer handler

            result.raw_data = rows

            # Step 4 — Generate EDA report
            logger.info("Generating EDA report (%d rows).", len(rows))
            report = await self._llm.generate_report(schema, query, rows)
            result.report = report

        except Exception as exc:
            logger.error("EDA pipeline failed: %s", exc, exc_info=True)
            result.error = str(exc)

        return result
