from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ProposedQuestion:
    """
    An EDA question automatically proposed by the question-generator agent.

    Attributes:
        question:         Natural language question suitable for text-to-SQL.
        relevant_tables:  Tables that the agent expects to need for this question.
        difficulty:       Estimated SQL complexity.
        category:         Broad analytical category.
    """

    question: str
    relevant_tables: list[str]
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    category: Literal["count", "distribution", "trend", "quality", "join", "other"] = "other"

    def display(self) -> str:
        icon = {"easy": "🟢", "medium": "🟡", "hard": "🔴"}.get(self.difficulty, "⚪")
        tables = ", ".join(self.relevant_tables)
        return f"{icon} [{self.category}] {self.question}  (tables: {tables})"
