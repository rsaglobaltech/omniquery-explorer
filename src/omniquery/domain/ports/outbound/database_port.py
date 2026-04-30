from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from omniquery.domain.entities.database_schema import DatabaseSchema


class DatabasePort(ABC):
    """
    Outbound port — defines the contract every DB adapter must fulfil.

    Implementations live in infrastructure/db/ and are injected at startup;
    the domain layer never imports them directly.
    """

    @abstractmethod
    async def get_schema(self, connection_url: str) -> DatabaseSchema:
        """
        Introspect the target database and return its full schema.

        Args:
            connection_url: SQLAlchemy async-compatible URL.

        Returns:
            A fully populated DatabaseSchema aggregate.
        """

    @abstractmethod
    async def execute_query(
        self, connection_url: str, sql: str, max_rows: int = 500
    ) -> list[dict[str, Any]]:
        """
        Execute a *read-only* SQL statement and return the rows as dicts.

        Implementations MUST reject any statement that is not a SELECT.

        Args:
            connection_url: SQLAlchemy async-compatible URL.
            sql:            The SELECT query to execute.
            max_rows:       Maximum number of rows to fetch.

        Returns:
            List of row dicts keyed by column name.

        Raises:
            ValueError: If the SQL contains non-SELECT statements.
            RuntimeError: On connection or execution errors.
        """
