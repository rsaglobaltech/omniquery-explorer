from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class ForeignKey:
    """Represents a FK constraint pointing to another table/column."""

    referred_table: str
    referred_column: str


@dataclass(frozen=True)
class Column:
    """
    Immutable value object representing a single column in a relational table.

    Attributes:
        name:           Column name as reported by the engine.
        sql_type:       Raw SQL type string (e.g. 'VARCHAR(255)', 'NUMBER(10,2)').
        nullable:       Whether the column accepts NULL values.
        is_primary_key: True if this column is part of the PK constraint.
        foreign_key:    FK descriptor if the column references another table, else None.
        comment:        Optional column-level comment / description from the DB catalogue.
    """

    name: str
    sql_type: str
    nullable: bool = True
    is_primary_key: bool = False
    foreign_key: Optional[ForeignKey] = None
    comment: Optional[str] = None

    def __str__(self) -> str:
        flags = []
        if self.is_primary_key:
            flags.append("PK")
        if self.foreign_key:
            flags.append(f"FK→{self.foreign_key.referred_table}.{self.foreign_key.referred_column}")
        if not self.nullable:
            flags.append("NOT NULL")
        flag_str = f" [{', '.join(flags)}]" if flags else ""
        return f"{self.name} {self.sql_type}{flag_str}"
