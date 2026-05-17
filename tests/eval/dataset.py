"""Dataset loader for the text-to-SQL eval harness.

Datasets are simple YAML files so they can be hand-curated and diffed
in PRs. Each dataset bundles a fixture DB (or DDL script) with a list
of natural-language cases.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class EvalCase:
    """A single (question → expected) pair."""

    id: str
    question: str
    # Optional ground-truth row set. When present, the runner compares
    # the executed rows against it (order-insensitive, value-equality).
    # When absent, success is "the query ran and returned at least one row".
    expected_rows: list[list[Any]] | None = None
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EvalDataset:
    """A complete eval bundle: fixture DB pointer + cases."""

    name: str
    connection_url: str
    ddl_path: Path | None
    cases: list[EvalCase]


def load_dataset(path: Path) -> EvalDataset:
    """Parse a YAML dataset file into typed objects."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    fixture = raw.get("fixture", {})
    ddl_path = fixture.get("ddl")
    cases = [
        EvalCase(
            id=c["id"],
            question=c["question"],
            expected_rows=c.get("expected_rows"),
            tags=list(c.get("tags", [])),
        )
        for c in raw.get("cases", [])
    ]
    return EvalDataset(
        name=raw.get("name", Path(path).stem),
        connection_url=fixture["url"],
        ddl_path=Path(ddl_path) if ddl_path else None,
        cases=cases,
    )
