from __future__ import annotations

from omniquery.infrastructure.db.sql_profiling_adapter import (
    _quote,
    _supports_information_schema,
)


class TestQuote:
    def test_postgres_uses_double_quote(self):
        assert _quote("postgresql+asyncpg://u:p@h/db", "users") == '"users"'

    def test_mysql_uses_backtick(self):
        assert _quote("mysql+aiomysql://u:p@h/db", "orders") == "`orders`"

    def test_mariadb_uses_backtick(self):
        assert _quote("mariadb+aiomysql://u:p@h/db", "orders") == "`orders`"

    def test_oracle_falls_back_to_double_quote(self):
        assert _quote("oracle+oracledb://u:p@h/db", "FOO") == '"FOO"'

    def test_mssql_uses_brackets(self):
        assert _quote("mssql+aioodbc://u:p@h/db", "Customer") == "[Customer]"

    def test_mssql_rejects_unsafe_bracket(self):
        import pytest

        with pytest.raises(ValueError):
            _quote("mssql+aioodbc://u:p@h/db", "Bad]name")

    def test_escapes_quote_characters(self):
        assert _quote("postgresql+asyncpg://u:p@h/db", 'we"ird') == '"we""ird"'
        assert _quote("mysql+aiomysql://u:p@h/db", "ba`d") == "`ba``d`"


class TestInformationSchemaSupport:
    def test_postgres_supported(self):
        assert _supports_information_schema("postgresql+asyncpg://u:p@h/db") is True

    def test_mysql_supported(self):
        assert _supports_information_schema("mysql+aiomysql://u:p@h/db") is True

    def test_oracle_not_supported(self):
        assert _supports_information_schema("oracle+oracledb://u:p@h/db") is False
