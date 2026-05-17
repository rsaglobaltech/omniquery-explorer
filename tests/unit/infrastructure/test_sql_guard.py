from __future__ import annotations

import pytest

from omniquery.domain.entities.database_schema import EngineType
from omniquery.infrastructure.db.sql_guard import (
    SqlGuardError,
    apply_limit,
    assert_read_only,
    referenced_tables,
    validate_against_schema,
)


class TestAssertReadOnly:
    def test_plain_select_passes(self):
        assert_read_only("SELECT 1", EngineType.POSTGRESQL)

    def test_select_with_join_passes(self):
        assert_read_only(
            "SELECT a.id, b.name FROM a JOIN b ON a.id = b.a_id",
            EngineType.POSTGRESQL,
        )

    def test_union_passes(self):
        assert_read_only(
            "SELECT 1 UNION SELECT 2",
            EngineType.POSTGRESQL,
        )

    def test_cte_select_passes(self):
        assert_read_only(
            "WITH cte AS (SELECT 1 AS n) SELECT * FROM cte",
            EngineType.POSTGRESQL,
        )

    @pytest.mark.parametrize(
        "sql",
        [
            "DROP TABLE users",
            "DELETE FROM users",
            "UPDATE users SET name='x'",
            "INSERT INTO users VALUES (1)",
            "TRUNCATE users",
            "ALTER TABLE users ADD COLUMN x INT",
        ],
    )
    def test_dml_and_ddl_rejected(self, sql):
        with pytest.raises(SqlGuardError):
            assert_read_only(sql, EngineType.POSTGRESQL)

    def test_cte_wrapped_dml_rejected(self):
        with pytest.raises(SqlGuardError):
            assert_read_only(
                "WITH x AS (DELETE FROM y RETURNING *) SELECT * FROM x",
                EngineType.POSTGRESQL,
            )

    def test_multiple_statements_rejected(self):
        with pytest.raises(SqlGuardError):
            assert_read_only(
                "SELECT 1; DROP TABLE users", EngineType.POSTGRESQL
            )

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT pg_sleep(10)",
            "SELECT * FROM dblink('host=evil', 'SELECT 1') AS t(c int)",
        ],
    )
    def test_forbidden_functions_rejected(self, sql):
        with pytest.raises(SqlGuardError):
            assert_read_only(sql, EngineType.POSTGRESQL)

    def test_unparseable_sql_rejected(self):
        with pytest.raises(SqlGuardError):
            assert_read_only("THIS IS NOT SQL", EngineType.POSTGRESQL)


class TestApplyLimit:
    def test_appends_limit_for_postgres(self):
        out = apply_limit("SELECT * FROM t", 100, EngineType.POSTGRESQL)
        assert "LIMIT 100" in out.upper()

    def test_appends_limit_for_mysql(self):
        out = apply_limit("SELECT * FROM t", 50, EngineType.MYSQL)
        assert "LIMIT 50" in out.upper()

    def test_uses_fetch_first_for_oracle(self):
        out = apply_limit("SELECT * FROM t", 25, EngineType.ORACLE)
        assert "FETCH FIRST" in out.upper()
        assert "25" in out

    def test_uses_fetch_first_for_mssql(self):
        out = apply_limit("SELECT * FROM t", 25, EngineType.MSSQL)
        assert "FETCH FIRST" in out.upper() or "FETCH NEXT" in out.upper()
        assert "25" in out

    def test_preserves_existing_limit(self):
        out = apply_limit("SELECT * FROM t LIMIT 5", 999, EngineType.POSTGRESQL)
        assert "LIMIT 5" in out.upper()
        assert "999" not in out

    def test_preserves_existing_fetch(self):
        out = apply_limit(
            "SELECT * FROM t FETCH FIRST 7 ROWS ONLY", 999, EngineType.ORACLE
        )
        assert "7" in out
        assert "999" not in out


class TestReferencedTables:
    def test_simple_from(self):
        assert referenced_tables(
            "SELECT * FROM customers", EngineType.POSTGRESQL
        ) == ["customers"]

    def test_join_and_alias(self):
        names = referenced_tables(
            "SELECT * FROM customers c JOIN orders o ON c.id = o.cid",
            EngineType.POSTGRESQL,
        )
        assert sorted(names) == ["customers", "orders"]

    def test_validate_against_schema_rejects_unknown(self):
        with pytest.raises(SqlGuardError):
            validate_against_schema(
                "SELECT * FROM ghost_table",
                known_tables=["customers", "orders"],
                engine=EngineType.POSTGRESQL,
            )

    def test_validate_against_schema_passes(self):
        validate_against_schema(
            "SELECT * FROM customers",
            known_tables=["customers", "orders"],
            engine=EngineType.POSTGRESQL,
        )
