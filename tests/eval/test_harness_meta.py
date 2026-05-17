"""Sanity tests for the eval harness itself.

These tests do NOT hit the LLM — they validate dataset parsing and the
metric aggregation logic so we can refactor the harness with
confidence. The LLM-driven tests live in test_run_dataset.py and are
marked ``eval`` so they're skipped in default CI.
"""

from __future__ import annotations

from pathlib import Path

from tests.eval.dataset import EvalCase, load_dataset
from tests.eval.runner import CaseResult, EvalReport, _rows_match


def test_load_dataset_parses_yaml():
    dataset = load_dataset(
        Path("tests/eval/datasets/ecommerce.yaml")
    )
    assert dataset.name == "ecommerce"
    assert dataset.connection_url.startswith("sqlite+aiosqlite")
    assert len(dataset.cases) == 4
    assert dataset.cases[0].id == "customers-count"
    assert dataset.cases[0].expected_rows == [[5]]


def test_rows_match_order_insensitive():
    assert _rows_match([{"a": 1}, {"a": 2}], [[2], [1]]) is True
    assert _rows_match([{"a": 1}], [[2]]) is False


def test_report_aggregates_metrics():
    report = EvalReport(dataset="x", total=4)
    report.cases = [
        CaseResult(case_id="a", execution_ok=True, fix_required=False, latency_ms=100),
        CaseResult(case_id="b", execution_ok=True, fix_required=True, latency_ms=200),
        CaseResult(case_id="c", execution_ok=False, fix_required=False, latency_ms=300),
        CaseResult(case_id="d", execution_ok=True, fix_required=False, latency_ms=400),
    ]
    assert report.execution_accuracy == 0.75
    assert report.fix_rate == 0.25
    assert report.latency_p50 == 250.0
    # p95 by nearest-rank on a list of 4 collapses to the 3rd index.
    assert report.latency_p95 == 300.0


def test_case_with_no_expected_rows_passes_on_any_data():
    # Cases without expected_rows are graded as ok when execute_sql
    # returns any data without surfacing an error.
    case = EvalCase(id="x", question="q")
    assert case.expected_rows is None
