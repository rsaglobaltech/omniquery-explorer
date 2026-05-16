"""PII protection policy.

Two responsibilities:

1. **Prompt redaction** — when sending DDL to the LLM, columns whose
   names match the denylist are stripped. The model never learns they
   exist, so it cannot ask for them in its SELECT.

2. **Result masking** — when results come back from the DB, any matched
   column is replaced with a configurable mask token (default ``***``).
   This is a defence-in-depth measure: if the model still asks for the
   column (or the user authored the SQL manually), the values never
   leave the application boundary.

Patterns are case-insensitive regex matched against the column name.
The default denylist covers the most common sensitive identifiers
(email, passwords, IDs, credit cards, addresses, ...). Tune via the
``PII_DENYLIST_PATTERNS`` env var.

This module is intentionally schema-agnostic — it operates on the
domain entities and row dicts so it can be plugged anywhere in the
pipeline (LLM adapter, web response shaper, CLI table renderer).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, replace
from typing import Any

from omniquery.config import PiiSettings
from omniquery.domain.entities.column import Column
from omniquery.domain.entities.database_schema import DatabaseSchema
from omniquery.domain.entities.table import Table

logger = logging.getLogger(__name__)


@dataclass
class PiiPolicy:
    """Stateless helper that knows what to hide and how to hide it."""

    settings: PiiSettings

    def __post_init__(self) -> None:
        # Pre-compile the denylist once; matching happens per column on
        # every prompt build and per row on every result, so cache it.
        if not self.settings.enabled or not self.settings.denylist_patterns:
            self._pattern: re.Pattern[str] | None = None
        else:
            # Allow simple comma-separated lists of bare names alongside
            # an inline regex. We join all patterns with '|' and wrap
            # them so a callable single pattern is used at match time.
            raw = self.settings.denylist_patterns.strip()
            self._pattern = re.compile(raw, re.IGNORECASE)

    # ------------------------------------------------------------------
    # Column matching
    # ------------------------------------------------------------------

    def is_sensitive(self, column_name: str) -> bool:
        """Return True when a column name matches the denylist."""
        if self._pattern is None:
            return False
        return bool(self._pattern.fullmatch(column_name))

    # ------------------------------------------------------------------
    # Schema redaction (prompt-side)
    # ------------------------------------------------------------------

    def redact_schema(self, schema: DatabaseSchema) -> DatabaseSchema:
        """Return a new schema with sensitive columns stripped out.

        The original aggregate is left untouched — callers receive a
        cloned instance safe to send to the LLM.
        """
        if self._pattern is None:
            return schema

        redacted_tables: list[Table] = []
        for table in schema.tables:
            # Filter columns. We do NOT keep a placeholder for the
            # removed column, otherwise the LLM might infer its existence
            # from the gap in ordinal positions.
            kept_columns: list[Column] = [
                c for c in table.columns if not self.is_sensitive(c.name)
            ]
            if len(kept_columns) != len(table.columns):
                logger.debug(
                    "pii: redacted %d column(s) from %s",
                    len(table.columns) - len(kept_columns),
                    table.name,
                )
            redacted_tables.append(
                Table(name=table.name, columns=kept_columns, comment=table.comment)
            )
        # ``replace`` on the dataclass gives a shallow copy so the engine
        # type and db_name carry over unchanged.
        return replace(schema, tables=redacted_tables)

    # ------------------------------------------------------------------
    # Result masking (response-side)
    # ------------------------------------------------------------------

    def mask_row(self, row: dict[str, Any]) -> dict[str, Any]:
        """Replace sensitive values in a single row dict."""
        if self._pattern is None:
            return row
        return {
            k: (self.settings.mask_value if self.is_sensitive(k) else v)
            for k, v in row.items()
        }

    def mask_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Vectorised version of mask_row over a list of rows."""
        if self._pattern is None or not rows:
            return rows
        return [self.mask_row(r) for r in rows]
