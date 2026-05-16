from __future__ import annotations

import pytest

from omniquery.config import PiiSettings
from omniquery.domain.entities.column import Column
from omniquery.domain.entities.database_schema import DatabaseSchema, EngineType
from omniquery.domain.entities.table import Table
from omniquery.infrastructure.governance.pii_policy import PiiPolicy


def _col(name: str) -> Column:
    return Column(name=name, sql_type="TEXT", nullable=True)


@pytest.fixture()
def schema() -> DatabaseSchema:
    return DatabaseSchema(
        engine=EngineType.POSTGRESQL,
        db_name="test",
        tables=[
            Table(
                name="customers",
                columns=[
                    _col("id"),
                    _col("name"),
                    _col("email"),
                    _col("phone_number"),
                ],
            ),
            Table(
                name="orders",
                columns=[_col("id"), _col("total"), _col("credit_card")],
            ),
        ],
    )


class TestSensitiveDetection:
    def test_matches_default_denylist(self):
        p = PiiPolicy(PiiSettings())
        assert p.is_sensitive("email") is True
        assert p.is_sensitive("PASSWORD") is True
        assert p.is_sensitive("phone_number") is True

    def test_safe_columns_not_flagged(self):
        p = PiiPolicy(PiiSettings())
        for safe in ("id", "name", "total", "created_at"):
            assert p.is_sensitive(safe) is False

    def test_disabled_means_nothing_flagged(self):
        p = PiiPolicy(PiiSettings(enabled=False))
        assert p.is_sensitive("email") is False


class TestRedactSchema:
    def test_removes_sensitive_columns(self, schema: DatabaseSchema):
        p = PiiPolicy(PiiSettings())
        out = p.redact_schema(schema)
        customers = out.get_table("customers")
        assert customers is not None
        names = [c.name for c in customers.columns]
        assert "email" not in names
        assert "phone_number" not in names
        assert "name" in names

    def test_original_schema_unmodified(self, schema: DatabaseSchema):
        original_cols = [c.name for c in schema.get_table("customers").columns]
        PiiPolicy(PiiSettings()).redact_schema(schema)
        after = [c.name for c in schema.get_table("customers").columns]
        assert original_cols == after  # purity

    def test_disabled_returns_schema_unchanged(self, schema: DatabaseSchema):
        p = PiiPolicy(PiiSettings(enabled=False))
        assert p.redact_schema(schema) is schema


class TestMaskRows:
    def test_replaces_sensitive_values(self):
        p = PiiPolicy(PiiSettings())
        rows = [
            {"id": 1, "name": "Ana", "email": "a@b.com", "phone_number": "+34..."},
            {"id": 2, "name": "Luis", "email": "x@y.com", "phone_number": "..."},
        ]
        masked = p.mask_rows(rows)
        assert masked[0]["email"] == "***"
        assert masked[0]["phone_number"] == "***"
        assert masked[0]["name"] == "Ana"
        assert masked[1]["email"] == "***"

    def test_empty_rows_pass_through(self):
        assert PiiPolicy(PiiSettings()).mask_rows([]) == []

    def test_custom_mask_value(self):
        p = PiiPolicy(PiiSettings(mask_value="<redacted>"))
        masked = p.mask_rows([{"email": "x@y.com"}])
        assert masked[0]["email"] == "<redacted>"
