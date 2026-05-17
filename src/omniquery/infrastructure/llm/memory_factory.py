"""Build a LangGraph checkpointer from ``MemorySettings``.

LangGraph's ``compile(checkpointer=...)`` accepts any
``BaseCheckpointSaver``. We expose ``resolve_checkpointer`` so the
container can pass one in or skip it altogether when memory is
disabled — keeping the EDA pipeline stateless by default.
"""

from __future__ import annotations

import logging
from typing import Any

from omniquery.config import MemorySettings

logger = logging.getLogger(__name__)


def resolve_checkpointer(settings: MemorySettings) -> Any | None:
    """Return a checkpointer instance, or ``None`` when memory is off.

    The return type is ``Any`` because LangGraph's saver types live in
    a separate optional package and we don't want to leak that import
    into callers that have memory disabled.
    """
    if not settings.enabled:
        return None

    if settings.backend == "memory":
        # ``MemorySaver`` is shipped with langgraph itself — no extra
        # dependency needed. It's perfectly fine for single-process
        # deployments where session continuity dies with the worker.
        from langgraph.checkpoint.memory import MemorySaver

        return MemorySaver()

    if settings.backend == "sqlite":
        # langgraph-checkpoint-sqlite is an optional extra. Import
        # lazily and emit a clear error if the user opted into 'sqlite'
        # without installing the package.
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "MEMORY_BACKEND=sqlite requires the 'langgraph-checkpoint-sqlite' "
                "package. Install with: uv sync --extra memory"
            ) from exc

        settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        return SqliteSaver.from_conn_string(str(settings.sqlite_path))

    logger.warning("Unknown memory backend %r — disabling memory.", settings.backend)
    return None
