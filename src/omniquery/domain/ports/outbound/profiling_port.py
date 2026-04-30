from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod

from omniquery.domain.entities.table_profile import TableProfile


class ProfilingPort(ABC):
    """
    Outbound port — statistical profiling of database tables.

    Implementations must query the underlying DB engine and return
    a TableProfile per table without modifying any data.
    """

    @abstractmethod
    async def profile_table(
        self,
        connection_url: str,
        table_name: str,
        sample_size: int = 5,
    ) -> TableProfile:
        """
        Return statistical metadata for a single table.

        Args:
            connection_url: SQLAlchemy async URL.
            table_name:     Unqualified table name.
            sample_size:    Number of sample rows to fetch.

        Returns:
            A populated TableProfile value object.
        """

    async def profile_all(
        self,
        connection_url: str,
        table_names: list[str],
        max_concurrent: int = 4,
        sample_size: int = 5,
    ) -> dict[str, TableProfile]:
        """
        Profile multiple tables concurrently, bounded by max_concurrent.

        This default implementation uses asyncio.Semaphore; subclasses can
        override for engine-specific batch queries.
        """
        semaphore = asyncio.Semaphore(max_concurrent)

        async def _bounded(name: str) -> tuple[str, TableProfile]:
            async with semaphore:
                try:
                    profile = await self.profile_table(connection_url, name, sample_size)
                except Exception:
                    # Return a minimal profile rather than failing the whole batch
                    profile = TableProfile(table_name=name)
                return name, profile

        results = await asyncio.gather(*[_bounded(n) for n in table_names])
        return dict(results)
