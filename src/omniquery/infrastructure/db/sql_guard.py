"""AST-based SQL safety and dialect rewriting.

Replaces the regex-based read-only check with a sqlglot parser. Provides:

- ``assert_read_only(sql, dialect)`` — raises ``SqlGuardError`` if the SQL
  is not a pure SELECT (rejects DML, DDL, CTE-wrapped DML, multiple
  statements, and a blocklist of dangerous functions).
- ``apply_limit(sql, max_rows, dialect)`` — dialect-aware LIMIT/FETCH
  injection using AST manipulation.
- ``validate_against_schema(sql, schema_table_names)`` — best-effort check
  that every table referenced in FROM/JOIN clauses exists in the schema.
"""

from __future__ import annotations

from typing import Iterable

import sqlglot
from sqlglot import exp

from omniquery.domain.entities.database_schema import EngineType


class SqlGuardError(ValueError):
    """Raised when SQL fails the safety policy."""


_ENGINE_TO_DIALECT = {
    EngineType.POSTGRESQL: "postgres",
    EngineType.MYSQL: "mysql",
    EngineType.ORACLE: "oracle",
}

_FORBIDDEN_FUNCTIONS = {
    "pg_sleep",
    "pg_read_file",
    "pg_read_binary_file",
    "lo_import",
    "lo_export",
    "dblink",
    "dblink_exec",
    "copy",
    "xp_cmdshell",
    "sleep",
    "benchmark",
    "load_file",
    "sys_exec",
    "utl_file",
    "utl_http",
    "dbms_lock",
}


def dialect_of(engine: EngineType) -> str:
    return _ENGINE_TO_DIALECT.get(engine, "")


def _parse_one(sql: str, dialect: str) -> exp.Expression:
    try:
        statements = sqlglot.parse(sql, read=dialect or None)
    except sqlglot.errors.ParseError as exc:
        raise SqlGuardError(f"SQL parse failed: {exc}") from exc

    statements = [s for s in statements if s is not None]
    if not statements:
        raise SqlGuardError("Empty SQL.")
    if len(statements) > 1:
        raise SqlGuardError(
            "Multiple statements detected; only a single SELECT is allowed."
        )
    return statements[0]


def assert_read_only(sql: str, engine: EngineType | None = None) -> exp.Expression:
    """Parse SQL and assert it is a single, pure SELECT.

    Returns the parsed root expression on success so callers can reuse it
    (e.g. to apply a LIMIT) without re-parsing.
    """
    dialect = dialect_of(engine) if engine else ""
    root = _parse_one(sql, dialect)

    if not isinstance(root, (exp.Select, exp.Union, exp.Subquery, exp.With)):
        raise SqlGuardError(
            f"Only SELECT/UNION statements are allowed (got {type(root).__name__})."
        )

    for node in root.walk():
        if isinstance(node, (exp.Insert, exp.Update, exp.Delete, exp.Merge)):
            raise SqlGuardError(
                f"DML detected inside query ({type(node).__name__.upper()})."
            )
        if isinstance(
            node,
            (exp.Create, exp.Drop, exp.Alter, exp.TruncateTable, exp.Command),
        ):
            raise SqlGuardError(
                f"DDL/admin statement detected ({type(node).__name__.upper()})."
            )
        if isinstance(node, exp.Anonymous):
            name = (node.this or "").lower() if isinstance(node.this, str) else ""
            if name in _FORBIDDEN_FUNCTIONS:
                raise SqlGuardError(f"Forbidden function in SQL: {name!r}.")
        if isinstance(node, exp.Func):
            name = node.sql_name().lower() if hasattr(node, "sql_name") else ""
            if name in _FORBIDDEN_FUNCTIONS:
                raise SqlGuardError(f"Forbidden function in SQL: {name!r}.")

    return root


def apply_limit(
    sql: str, max_rows: int, engine: EngineType | None = None
) -> str:
    """Apply a dialect-aware row limit.

    PostgreSQL/MySQL → ``LIMIT n``.
    Oracle → ``FETCH FIRST n ROWS ONLY``.

    If the statement already includes a LIMIT/FETCH, it is left intact.
    """
    dialect = dialect_of(engine) if engine else ""
    root = _parse_one(sql, dialect)

    has_limit = any(isinstance(n, (exp.Limit, exp.Fetch)) for n in root.walk())
    if has_limit:
        return root.sql(dialect=dialect or None)

    if engine == EngineType.ORACLE:
        fetched = root.copy()
        fetched.set(
            "limit",
            exp.Fetch(direction="FIRST", count=exp.Literal.number(max_rows)),
        )
        return fetched.sql(dialect="oracle")

    limited = root.copy().limit(max_rows)
    return limited.sql(dialect=dialect or None)


def referenced_tables(sql: str, engine: EngineType | None = None) -> list[str]:
    """Return unique base-table names referenced by the query."""
    dialect = dialect_of(engine) if engine else ""
    root = _parse_one(sql, dialect)
    names: list[str] = []
    seen: set[str] = set()
    for node in root.find_all(exp.Table):
        name = node.name
        if name and name.lower() not in seen:
            seen.add(name.lower())
            names.append(name)
    return names


def validate_against_schema(
    sql: str,
    known_tables: Iterable[str],
    engine: EngineType | None = None,
) -> None:
    """Reject SQL that references tables not present in the schema."""
    known_lower = {t.lower() for t in known_tables}
    referenced = referenced_tables(sql, engine)
    unknown = [t for t in referenced if t.lower() not in known_lower]
    if unknown:
        raise SqlGuardError(
            "Query references unknown tables: " + ", ".join(unknown)
        )
