"""Eval harness runner.

Runs each case through the full pipeline (`RunEdaUseCase.run_eda`) and
collects metrics. Designed to be driven both from pytest (one test per
case via parametrize) and standalone (`python -m tests.eval.runner`).
"""

from __future__ import annotations

import asyncio
import statistics
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import text

from omniquery.domain.entities.eda_query import EdaQuery
from omniquery.infrastructure.container import get_container
from omniquery.infrastructure.db.engine_pool import get_default_pool
from tests.eval.dataset import EvalCase, EvalDataset


@dataclass
class CaseResult:
    """Per-case telemetry returned by the runner."""

    case_id: str
    execution_ok: bool
    fix_required: bool
    latency_ms: float
    error: str = ""
    generated_sql: str = ""
    row_count: int = 0


@dataclass
class EvalReport:
    """Aggregate metrics across a dataset run."""

    dataset: str
    total: int
    cases: list[CaseResult] = field(default_factory=list)

    @property
    def execution_accuracy(self) -> float:
        if not self.cases:
            return 0.0
        return sum(1 for c in self.cases if c.execution_ok) / len(self.cases)

    @property
    def fix_rate(self) -> float:
        if not self.cases:
            return 0.0
        return sum(1 for c in self.cases if c.fix_required) / len(self.cases)

    @property
    def latency_p50(self) -> float:
        values = [c.latency_ms for c in self.cases] or [0.0]
        return statistics.median(values)

    @property
    def latency_p95(self) -> float:
        values = sorted(c.latency_ms for c in self.cases)
        if not values:
            return 0.0
        # 95th percentile by nearest-rank — adequate for small samples.
        idx = max(0, int(len(values) * 0.95) - 1)
        return values[idx]

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset,
            "total": self.total,
            "execution_accuracy": self.execution_accuracy,
            "fix_rate": self.fix_rate,
            "latency_p50_ms": self.latency_p50,
            "latency_p95_ms": self.latency_p95,
            "cases": [asdict(c) for c in self.cases],
        }


async def _ensure_fixture(connection_url: str, ddl_path: Path | None) -> None:
    """Apply the dataset's DDL to the fixture DB if provided.

    We rely on the shared pool so the test eval doesn't create yet
    another engine outside the lifecycle.
    """
    if ddl_path is None:
        return
    sql_script = Path(ddl_path).read_text(encoding="utf-8")
    engine = await get_default_pool().get(connection_url)
    async with engine.begin() as conn:
        # Execute statement-by-statement; many DBs reject multi-statement
        # strings via the SQLAlchemy text() driver.
        for stmt in [s.strip() for s in sql_script.split(";") if s.strip()]:
            await conn.execute(text(stmt))


def _rows_match(actual: list[dict[str, Any]], expected: list[list[Any]]) -> bool:
    """Compare result sets order-insensitively by their tuple representation."""
    actual_tuples = sorted(tuple(r.values()) for r in actual)
    expected_tuples = sorted(tuple(r) for r in expected)
    return actual_tuples == expected_tuples


async def run_case(case: EvalCase, dataset: EvalDataset) -> CaseResult:
    """Execute a single case end-to-end and capture metrics."""
    container = get_container()
    use_case = container.eda_use_case(dataset.connection_url)
    start = time.perf_counter()
    result = await use_case.run_eda(
        EdaQuery(
            question=case.question,
            connection_url=dataset.connection_url,
            max_rows=200,
        )
    )
    latency = round((time.perf_counter() - start) * 1000, 2)

    # AnalysisResult does not yet expose retry attempts. We approximate
    # `fix_required` by checking the persisted store; for now derive
    # from presence of a non-empty error then a successful retry path.
    fix_required = bool(result.error == "" and "fix" in (result.report or "").lower())

    if case.expected_rows is not None:
        execution_ok = _rows_match(result.raw_data, case.expected_rows)
    else:
        execution_ok = bool(result.raw_data) and not result.error

    return CaseResult(
        case_id=case.id,
        execution_ok=execution_ok,
        fix_required=fix_required,
        latency_ms=latency,
        error=result.error,
        generated_sql=result.generated_sql or "",
        row_count=result.row_count,
    )


async def run_dataset(dataset: EvalDataset) -> EvalReport:
    """Run every case in a dataset sequentially (to avoid hammering the LLM)."""
    await _ensure_fixture(dataset.connection_url, dataset.ddl_path)
    report = EvalReport(dataset=dataset.name, total=len(dataset.cases))
    for case in dataset.cases:
        report.cases.append(await run_case(case, dataset))
    return report


def main(dataset_path: str) -> None:
    """CLI entry point — print a JSON report to stdout."""
    import json

    from tests.eval.dataset import load_dataset

    dataset = load_dataset(Path(dataset_path))
    report = asyncio.run(run_dataset(dataset))
    print(json.dumps(report.to_dict(), indent=2, default=str))


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("usage: python -m tests.eval.runner <dataset.yaml>")
        sys.exit(1)
    main(sys.argv[1])
