from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class EdaQuery:
    """
    Immutable Value Object that encapsulates a single user request.

    Attributes:
        question:       The natural language question from the user.
        connection_url: SQLAlchemy-compatible database URL
                        (e.g. 'postgresql+asyncpg://user:pw@host/db').
        max_rows:       Optional hard cap on rows returned to prevent runaway queries.
                        Defaults to 500 during exploratory phases.
    """

    question: str
    connection_url: str
    max_rows: int = 500

    def __post_init__(self) -> None:
        if not self.question.strip():
            raise ValueError("EdaQuery.question must not be empty.")
        if not self.connection_url.strip():
            raise ValueError("EdaQuery.connection_url must not be empty.")
        if self.max_rows < 1:
            raise ValueError("EdaQuery.max_rows must be a positive integer.")
