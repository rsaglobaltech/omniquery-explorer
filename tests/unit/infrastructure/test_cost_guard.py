from __future__ import annotations

import pytest

from omniquery.config import CostGuardSettings
from omniquery.infrastructure.governance.cost_guard import (
    BudgetExceeded,
    BudgetTracker,
    CostGuardError,
    _check_thresholds,
    _mysql_estimated_rows,
)


class TestBudgetTracker:
    def test_increments_until_cap(self):
        bt = BudgetTracker(CostGuardSettings(max_queries_per_session=3))
        bt.register_query("s1")
        bt.register_query("s1")
        bt.register_query("s1")
        with pytest.raises(BudgetExceeded):
            bt.register_query("s1")

    def test_sessions_isolated(self):
        bt = BudgetTracker(CostGuardSettings(max_queries_per_session=1))
        bt.register_query("s1")
        # s2 has its own bucket — should not be impacted by s1's count.
        bt.register_query("s2")
        with pytest.raises(BudgetExceeded):
            bt.register_query("s1")

    def test_tokens_capped(self):
        bt = BudgetTracker(CostGuardSettings(max_tokens_per_session=1000))
        bt.register_tokens("s", 600)
        bt.register_tokens("s", 400)
        with pytest.raises(BudgetExceeded):
            bt.register_tokens("s", 1)

    def test_zero_or_negative_tokens_ignored(self):
        bt = BudgetTracker(CostGuardSettings(max_tokens_per_session=10))
        bt.register_tokens("s", 0)
        bt.register_tokens("s", -50)
        assert bt.snapshot("s")["tokens"] == 0


class TestCheckThresholds:
    def test_cost_breach(self):
        with pytest.raises(CostGuardError):
            _check_thresholds(
                cost=2e6,
                rows_est=10,
                settings=CostGuardSettings(max_plan_cost=1e6),
            )

    def test_rows_breach(self):
        with pytest.raises(CostGuardError):
            _check_thresholds(
                cost=0.0,
                rows_est=100_000_000,
                settings=CostGuardSettings(max_plan_rows=50_000_000),
            )

    def test_passes_when_under_limits(self):
        _check_thresholds(
            cost=10.0,
            rows_est=1000,
            settings=CostGuardSettings(),
        )


class TestMysqlEstimatedRows:
    def test_extracts_largest_rows_from_plan(self):
        plan = {
            "query_block": {
                "table": {"rows_examined_per_scan": 1234},
                "nested_loop": [
                    {"table": {"rows_examined_per_scan": 99}},
                    {"table": {"rows_examined_per_scan": 9999}},
                ],
            }
        }
        assert _mysql_estimated_rows(plan) == 9999

    def test_empty_plan_returns_zero(self):
        assert _mysql_estimated_rows({}) == 0
