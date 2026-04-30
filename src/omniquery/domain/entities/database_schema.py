from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from omniquery.domain.entities.table import Table


class EngineType(str, Enum):
    POSTGRESQL = "postgresql"
    MYSQL = "mysql"
    ORACLE = "oracle"


@dataclass
class DatabaseSchema:
    """
    Aggregate Root representing the full schema of a connected database.

    Holds all introspected tables and carries enough context for the LLM
    to infer the business domain without touching the underlying engine again.

    Attributes:
        engine:     The RDBMS engine type.
        tables:     All tables discovered during introspection.
        db_name:    Database / service name as reported by the engine.
        schema_name: Optional schema/namespace (e.g. PostgreSQL search_path,
                     Oracle schema, MySQL database name).
    """

    engine: EngineType
    tables: list[Table] = field(default_factory=list)
    db_name: Optional[str] = None
    schema_name: Optional[str] = None

    # ------------------------------------------------------------------
    # Convenience accessors
    # ------------------------------------------------------------------

    def get_table(self, name: str) -> Optional[Table]:
        """Look up a table by name (case-insensitive)."""
        name_lower = name.lower()
        return next((t for t in self.tables if t.name.lower() == name_lower), None)

    @property
    def table_names(self) -> list[str]:
        return [t.name for t in self.tables]

    def to_ddl_summary(self, max_tables: int = 40, exclude_pattern: str | None = None) -> str:
        """
        Produce a compact DDL-like summary suitable for injection into an LLM prompt
        inside the <schema_definition> tag.

        Args:
            max_tables:      Cap the number of tables included (avoids token overflow
                             with large schemas). Partition/xref tables are deprioritised.
            exclude_pattern: Regex pattern — tables whose names match are excluded.
                             Defaults to filtering out common partition suffixes.
        """
        import re

        # Default: skip obvious partition tables (xref_pN_*, xref_pN_not_deleted, etc.)
        _exclude = exclude_pattern or r"^xref_p\d+"

        filtered = [
            t for t in self.tables
            if not re.match(_exclude, t.name, re.IGNORECASE)
        ]

        # Fall back to all tables if filtering leaves nothing
        candidates = filtered if filtered else self.tables
        candidates = candidates[:max_tables]

        lines: list[str] = []
        for table in candidates:
            col_defs = ",\n  ".join(str(c) for c in table.columns)
            lines.append(f"TABLE {table.name} (\n  {col_defs}\n);")

        skipped = len(self.tables) - len(candidates)
        if skipped > 0:
            lines.append(f"-- ... and {skipped} more tables omitted for brevity")

        return "\n\n".join(lines)

    def exact_ddl(self, table_names: list[str]) -> str:
        """
        Return the full CREATE TABLE DDL (with every column) for the given tables.

        Used by the LLM fix loop to inject *verified* schema snippets so the
        model cannot hallucinate column names.

        Args:
            table_names: List of table names to include (case-insensitive lookup).

        Returns:
            DDL string, or an empty string if none of the tables are found.
        """
        lines: list[str] = []
        for name in table_names:
            table = self.get_table(name)
            if table is None:
                lines.append(f"-- WARNING: table '{name}' NOT FOUND in schema")
                continue
            col_defs = ",\n  ".join(str(c) for c in table.columns)
            col_names = ", ".join(c.name for c in table.columns)
            lines.append(
                f"-- EXACT COLUMNS for {table.name}: {col_names}\n"
                f"TABLE {table.name} (\n  {col_defs}\n);"
            )
        return "\n\n".join(lines)

    def __str__(self) -> str:
        return (
            f"DatabaseSchema(engine={self.engine.value}, "
            f"db={self.db_name}, tables={self.table_names})"
        )
