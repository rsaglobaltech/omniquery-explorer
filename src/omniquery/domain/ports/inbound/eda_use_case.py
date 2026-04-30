from __future__ import annotations

from abc import ABC, abstractmethod

from omniquery.domain.entities.analysis_result import AnalysisResult
from omniquery.domain.entities.eda_query import EdaQuery


class EdaUseCase(ABC):
    """
    Inbound port — the single entry point exposed to all driving adapters
    (CLI, Web API).

    Driving adapters receive a concrete implementation via dependency
    injection and call run_eda(); they never touch the domain entities
    or infrastructure adapters directly.
    """

    @abstractmethod
    async def run_eda(self, query: EdaQuery) -> AnalysisResult:
        """
        Orchestrate the full EDA pipeline for a single user question.

        Steps (implemented in application/use_cases/run_eda_use_case.py):
            1. Introspect DB schema via DatabasePort.
            2. Ask LLM to generate SQL via LlmPort.
            3. Execute SQL via DatabasePort.
            4. Ask LLM to generate EDA report via LlmPort.
            5. Return a populated AnalysisResult.

        Args:
            query: The user's question and connection details.

        Returns:
            AnalysisResult with generated_sql, raw_data, and report populated,
            or with error set if any step failed gracefully.
        """
