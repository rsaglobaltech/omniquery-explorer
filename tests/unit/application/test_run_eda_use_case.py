"""Unit tests for RunEdaUseCase.

Hand-rolled fake adapters keep these tests fast and deterministic — we
intentionally avoid mocking libraries so the contracts under test
(`DatabasePort`, `LlmPort`, `PiiPolicy`, `BudgetTracker`) stay loosely
coupled to the concrete implementations.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.exc import ProgrammingError

from omniquery.application.use_cases.run_eda_use_case import RunEdaUseCase
from omniquery.config import CostGuardSettings, PiiSettings
from omniquery.domain.entities.database_schema import DatabaseSchema
from omniquery.domain.entities.eda_query import EdaQuery
from omniquery.domain.ports.outbound.database_port import DatabasePort
from omniquery.domain.ports.outbound.llm_port import LlmPort
from omniquery.infrastructure.governance.cost_guard import BudgetTracker
from omniquery.infrastructure.governance.pii_policy import PiiPolicy


class FakeDB(DatabasePort):
    """Minimal DatabasePort: returns a fixed schema and either rows or an error."""

    def __init__(
        self,
        schema: DatabaseSchema,
        rows: list[dict[str, Any]] | None = None,
        raise_on_attempt: int | None = None,
    ) -> None:
        self._schema = schema
        self._rows = rows or []
        # 0-indexed attempt that should raise ProgrammingError before
        # returning rows. None means never raise.
        self._raise_on_attempt = raise_on_attempt
        self.execute_calls: list[str] = []

    async def get_schema(self, connection_url: str) -> DatabaseSchema:
        return self._schema

    async def execute_query(
        self, connection_url: str, sql: str, max_rows: int = 500
    ) -> list[dict[str, Any]]:
        self.execute_calls.append(sql)
        if (
            self._raise_on_attempt is not None
            and len(self.execute_calls) - 1 == self._raise_on_attempt
        ):
            # Use ProgrammingError so RunEdaUseCase routes into fix_sql.
            raise ProgrammingError("SELECT bad", {}, Exception("syntax error"))
        return self._rows


class FakeLLM(LlmPort):
    """LlmPort fake that records prompts and yields scripted responses."""

    def __init__(
        self,
        sql: str = "SELECT * FROM customers",
        fixed_sql: str = "SELECT id FROM customers",
        report: str = "# Report\nMain finding...",
    ) -> None:
        self._sql = sql
        self._fixed_sql = fixed_sql
        self._report = report
        self.generate_sql_schema_columns: list[list[str]] = []
        self.report_rows: list[list[dict[str, Any]]] = []
        self.fix_called = 0

    async def chat(self, prompt: str, *, call_name: str = "chat") -> str:
        return ""

    async def generate_sql(self, schema, query):
        # Record which column names made it through (PII redaction check).
        cols = [c.name for t in schema.tables for c in t.columns]
        self.generate_sql_schema_columns.append(cols)
        return self._sql

    async def fix_sql(self, schema, query, bad_sql, error):
        self.fix_called += 1
        return self._fixed_sql

    async def generate_report(self, schema, query, results):
        self.report_rows.append(results)
        return self._report


@pytest.fixture()
def query(simple_schema: DatabaseSchema) -> EdaQuery:
    # connection_url is opaque to the fakes; only used as a budget key.
    return EdaQuery(
        question="Top customers?",
        connection_url="fake://test/db",
        max_rows=50,
    )


@pytest.mark.asyncio
async def test_happy_path_returns_sql_rows_report(
    simple_schema: DatabaseSchema, query: EdaQuery
) -> None:
    rows = [{"id": 1, "name": "Ana"}]
    db = FakeDB(simple_schema, rows=rows)
    llm = FakeLLM()
    use_case = RunEdaUseCase(db=db, llm=llm)

    result = await use_case.run_eda(query)

    assert not result.error
    assert result.generated_sql == "SELECT * FROM customers"
    assert result.raw_data == rows
    assert result.report.startswith("# Report")
    assert len(db.execute_calls) == 1
    assert llm.fix_called == 0


@pytest.mark.asyncio
async def test_fix_sql_invoked_on_first_failure(
    simple_schema: DatabaseSchema, query: EdaQuery
) -> None:
    """When the first execute_query raises, the LLM must be asked to fix it."""
    db = FakeDB(simple_schema, rows=[{"id": 1}], raise_on_attempt=0)
    llm = FakeLLM()
    use_case = RunEdaUseCase(db=db, llm=llm)

    result = await use_case.run_eda(query)

    assert not result.error
    assert llm.fix_called == 1
    # First call used original SQL, second used the fixed SQL.
    assert db.execute_calls[0] == "SELECT * FROM customers"
    assert db.execute_calls[1] == "SELECT id FROM customers"


@pytest.mark.asyncio
async def test_budget_exhaustion_short_circuits(
    simple_schema: DatabaseSchema, query: EdaQuery
) -> None:
    """An exhausted budget must produce a fail-fast error without DB or LLM calls."""
    budget = BudgetTracker(CostGuardSettings(max_queries_per_session=0))
    db = FakeDB(simple_schema, rows=[{"id": 1}])
    llm = FakeLLM()
    use_case = RunEdaUseCase(db=db, llm=llm, budget=budget)

    result = await use_case.run_eda(query)

    assert "max_queries_per_session" in result.error
    assert db.execute_calls == []
    # generate_sql must not have been called either.
    assert llm.generate_sql_schema_columns == []


@pytest.mark.asyncio
async def test_pii_redacts_schema_and_masks_rows(
    simple_schema: DatabaseSchema, query: EdaQuery
) -> None:
    """The LLM must never see 'email', and 'email' values must be masked."""
    pii = PiiPolicy(PiiSettings())  # default denylist covers 'email'
    db = FakeDB(simple_schema, rows=[{"id": 1, "email": "a@b.com", "name": "Ana"}])
    llm = FakeLLM()
    use_case = RunEdaUseCase(db=db, llm=llm, pii=pii)

    result = await use_case.run_eda(query)

    # Schema passed to generate_sql must NOT contain 'email'.
    assert "email" not in llm.generate_sql_schema_columns[0]
    # Returned rows have 'email' replaced with the default mask.
    assert result.raw_data[0]["email"] == "***"
    assert result.raw_data[0]["name"] == "Ana"


@pytest.mark.asyncio
async def test_db_failure_surfaces_after_retry_exhaustion(
    simple_schema: DatabaseSchema, query: EdaQuery
) -> None:
    """If every attempt fails the error propagates into result.error."""

    # Custom DB that ALWAYS raises.
    class AlwaysFailDB(FakeDB):
        async def execute_query(self, connection_url, sql, max_rows=500):
            self.execute_calls.append(sql)
            raise ProgrammingError("bad", {}, Exception("always fails"))

    db = AlwaysFailDB(simple_schema)
    llm = FakeLLM()
    use_case = RunEdaUseCase(db=db, llm=llm)

    result = await use_case.run_eda(query)

    assert result.error
    # Retry loop = initial + _MAX_SQL_RETRIES (2) = 3 attempts.
    assert len(db.execute_calls) == 3
    assert llm.fix_called == 2
