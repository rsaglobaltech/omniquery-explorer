from __future__ import annotations

from dataclasses import dataclass, field


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
        hint_tables:    Optional list of table names pre-selected by semantic schema
                        linking (P1).  When present, the LLM adapters prioritise these
                        tables in the Phase A selection step.
    """

    question: str
    connection_url: str
    max_rows: int = 500
    hint_tables: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.question.strip():
            raise ValueError("EdaQuery.question must not be empty.")
        if not self.connection_url.strip():
            raise ValueError("EdaQuery.connection_url must not be empty.")
        if self.max_rows < 1:
            raise ValueError("EdaQuery.max_rows must be a positive integer.")
        # Normalise hint_tables to a tuple (callers may pass a list)
        object.__setattr__(self, "hint_tables", tuple(self.hint_tables))
