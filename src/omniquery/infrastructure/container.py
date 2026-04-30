from __future__ import annotations

from functools import lru_cache

from omniquery.application.agents.eda_session_graph import EdaSessionGraph
from omniquery.application.use_cases.run_eda_use_case import RunEdaUseCase
from omniquery.domain.ports.inbound.eda_use_case import EdaUseCase
from omniquery.infrastructure.db.adapter_factory import resolve_db_adapter
from omniquery.infrastructure.db.sql_profiling_adapter import SqlProfilingAdapter
from omniquery.infrastructure.llm.ollama_adapter import OllamaAdapter


class Container:
    """
    Lightweight dependency-injection container.

    Builds and caches the object graph at first access so that both the
    CLI and the Web adapter share the same singletons without a heavy
    DI framework.

    Configuration is read from environment variables (with sensible defaults):
        OLLAMA_MODEL    — Ollama model name           (default: "llama3.2:latest")
        OLLAMA_BASE_URL — Ollama server URL            (default: "http://localhost:11434")
        OLLAMA_TIMEOUT  — HTTP timeout in seconds      (default: "300")
    """

    def __init__(
        self,
        ollama_model: str = "llama3.2:latest",
        ollama_base_url: str = "http://localhost:11434",
        ollama_timeout: float = 300.0,
    ) -> None:
        self._ollama_model = ollama_model
        self._ollama_base_url = ollama_base_url
        self._ollama_timeout = ollama_timeout
        self._llm = OllamaAdapter(
            model=self._ollama_model,
            base_url=self._ollama_base_url,
            timeout=self._ollama_timeout,
        )
        self._profiler = SqlProfilingAdapter()

    def eda_use_case(self, connection_url: str) -> EdaUseCase:
        """
        Return a RunEdaUseCase wired with the correct DB adapter for the
        given connection URL and the shared LLM adapter.
        """
        db_adapter = resolve_db_adapter(connection_url)
        return RunEdaUseCase(db=db_adapter, llm=self._llm)

    def eda_session_graph(self, connection_url: str) -> EdaSessionGraph:
        """
        Return an EdaSessionGraph (LangGraph) wired for the given DB URL.
        The LLM and profiler adapters are shared singletons.
        """
        db_adapter = resolve_db_adapter(connection_url)
        return EdaSessionGraph(db=db_adapter, llm=self._llm, profiler=self._profiler)


@lru_cache(maxsize=1)
def get_container() -> Container:
    """
    Return the process-wide singleton Container, configured from env vars.
    Calling code should use this rather than instantiating Container directly.
    """
    import os

    return Container(
        ollama_model=os.getenv("OLLAMA_MODEL", "llama3.2:latest"),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        ollama_timeout=float(os.getenv("OLLAMA_TIMEOUT", "300")),
    )
