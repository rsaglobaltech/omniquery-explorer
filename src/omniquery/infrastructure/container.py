from __future__ import annotations

from functools import lru_cache

from omniquery.application.agents.eda_session_graph import EdaSessionGraph
from omniquery.application.use_cases.run_eda_use_case import RunEdaUseCase
from omniquery.config import Settings, get_settings
from omniquery.domain.ports.inbound.eda_use_case import EdaUseCase
from omniquery.domain.ports.outbound.llm_port import LlmPort
from omniquery.infrastructure.db.adapter_factory import resolve_db_adapter
from omniquery.infrastructure.db.sql_profiling_adapter import SqlProfilingAdapter
from omniquery.infrastructure.graph.schema_linker import SchemaLinker
from omniquery.infrastructure.llm.llm_factory import resolve_llm_adapter
from omniquery.infrastructure.llm.ollama_embedding_adapter import OllamaEmbeddingAdapter


class Container:
    """
    Lightweight dependency-injection container.

    Builds and caches the object graph at first access so that both the
    CLI and the Web adapter share the same singletons without a heavy
    DI framework. Configuration is supplied via the typed `Settings`
    module (see `omniquery.config`).
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._llm: LlmPort = resolve_llm_adapter(self._settings.llm)
        self._emb = OllamaEmbeddingAdapter(
            model=self._settings.llm.embedding_model,
            base_url=self._settings.llm.ollama_base_url,
        )
        self._schema_linker = SchemaLinker(self._emb)
        self._profiler = SqlProfilingAdapter()

    @property
    def settings(self) -> Settings:
        return self._settings

    def eda_use_case(self, connection_url: str) -> EdaUseCase:
        db_adapter = resolve_db_adapter(connection_url)
        return RunEdaUseCase(db=db_adapter, llm=self._llm)

    def eda_session_graph(self, connection_url: str) -> EdaSessionGraph:
        db_adapter = resolve_db_adapter(connection_url)
        return EdaSessionGraph(
            db=db_adapter,
            llm=self._llm,
            profiler=self._profiler,
            schema_linker=self._schema_linker,
        )


@lru_cache(maxsize=1)
def get_container() -> Container:
    """Return the process-wide singleton Container."""
    return Container(get_settings())
