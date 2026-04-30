from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from omniquery.domain.entities.column import Column


@dataclass
class Table:
    """
    Represents a relational table extracted from the database catalogue.

    Attributes:
        name:    Table name (unqualified; schema prefix handled by DatabaseSchema).
        columns: Ordered list of Column objects as they appear in the DDL.
        comment: Optional table-level comment from the DB catalogue.
    """

    name: str
    columns: list[Column] = field(default_factory=list)
    comment: Optional[str] = None

    # ------------------------------------------------------------------
    # Convenience accessors
    # ------------------------------------------------------------------

    @property
    def primary_keys(self) -> list[Column]:
        """Return all columns that are part of the primary key."""
        return [c for c in self.columns if c.is_primary_key]

    @property
    def foreign_keys(self) -> list[Column]:
        """Return all columns that carry a FK constraint."""
        return [c for c in self.columns if c.foreign_key is not None]

    def get_column(self, name: str) -> Optional[Column]:
        """Look up a column by name (case-insensitive)."""
        name_lower = name.lower()
        return next((c for c in self.columns if c.name.lower() == name_lower), None)

    def __str__(self) -> str:
        cols = ", ".join(str(c) for c in self.columns)
        return f"Table({self.name})[{cols}]"
