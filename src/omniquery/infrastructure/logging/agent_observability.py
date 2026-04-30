from __future__ import annotations

import json
import logging
import os
from contextlib import contextmanager
from contextvars import ContextVar, Token
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

_CONTEXT: ContextVar[dict[str, Any]] = ContextVar("omniquery_log_context", default={})
_RESERVED_RECORD_ATTRS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys())


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, min_value: int = 0) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return max(min_value, int(value))
    except ValueError:
        return default


def get_payload_limit() -> int:
    return _env_int("OMNIQUERY_LOG_PAYLOAD_CHARS", 600, min_value=100)


def get_log_context() -> dict[str, Any]:
    return dict(_CONTEXT.get())


def set_log_context(**fields: Any) -> Token[dict[str, Any]]:
    merged = get_log_context()
    for key, value in fields.items():
        if value is not None:
            merged[key] = value
    return _CONTEXT.set(merged)


def reset_log_context(token: Token[dict[str, Any]]) -> None:
    _CONTEXT.reset(token)


@contextmanager
def log_context(**fields: Any) -> Iterator[None]:
    token = set_log_context(**fields)
    try:
        yield
    finally:
        reset_log_context(token)


class ContextFilter(logging.Filter):
    """Inject contextvars into each log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in get_log_context().items():
            if not hasattr(record, key):
                setattr(record, key, value)
        return True


class AgentFilter(logging.Filter):
    """Allow only selected agent names when OMNIQUERY_LOG_AGENT is set."""

    def __init__(self, allowed: str | None) -> None:
        super().__init__()
        self._allowed = {
            item.strip().lower() for item in (allowed or "").split(",") if item.strip()
        }

    def filter(self, record: logging.LogRecord) -> bool:
        if not self._allowed:
            return True
        agent = getattr(record, "agent", None)
        if not agent:
            return False
        return str(agent).lower() in self._allowed


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        details: list[str] = []
        for key in ("session_id", "agent", "event"):
            value = getattr(record, key, None)
            if value:
                details.append(f"{key}={value}")
        return f"{base} [{' '.join(details)}]" if details else base


class JsonFormatter(logging.Formatter):
    """Structured JSON logs suitable for search and dashboards."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        for key in (
            "session_id",
            "agent",
            "event",
            "duration_ms",
            "tokens",
            "context",
            "input",
            "output",
            "error",
        ):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value

        extras: dict[str, Any] = {}
        for key, value in record.__dict__.items():
            if key in _RESERVED_RECORD_ATTRS or key in payload:
                continue
            if key.startswith("_"):
                continue
            extras[key] = value
        if extras:
            payload["extra"] = extras

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(force: bool = False) -> None:
    """
    Configure root logging once.

    Env vars:
      - OMNIQUERY_LOG_LEVEL: DEBUG/INFO/WARNING/... (default INFO)
      - OMNIQUERY_LOG_FORMAT: json|text (default text)
      - OMNIQUERY_LOG_AGENT: optional comma-separated agent filter
      - OMNIQUERY_LOG_PAYLOAD_CHARS: max chars for prompt/response snapshots
      - OMNIQUERY_LOG_DIR: directory for log files (default .logs)
      - OMNIQUERY_LOG_FILE: file name (default omniquery-YYYY-MM-DD.logs)
      - OMNIQUERY_LOG_FORCE: true to override existing handlers
    """
    should_force = force or _env_bool("OMNIQUERY_LOG_FORCE", False)
    root = logging.getLogger()
    if root.handlers and not should_force:
        return

    level_name = os.getenv("OMNIQUERY_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    fmt = os.getenv("OMNIQUERY_LOG_FORMAT", "text").strip().lower()

    shared_filters = [
        ContextFilter(),
        AgentFilter(os.getenv("OMNIQUERY_LOG_AGENT")),
    ]
    log_dir = Path(os.getenv("OMNIQUERY_LOG_DIR", ".logs"))
    log_dir.mkdir(parents=True, exist_ok=True)
    default_log_file = f"omniquery-{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.logs"
    raw_log_file = os.getenv("OMNIQUERY_LOG_FILE")
    log_file = raw_log_file.strip() if raw_log_file and raw_log_file.strip() else default_log_file

    file_candidate = Path(log_file)
    if file_candidate.is_absolute():
        log_path = file_candidate
    else:
        log_path = log_dir / file_candidate

    # If caller provided a directory path by mistake, write default file inside it.
    if log_path.exists() and log_path.is_dir():
        log_path = log_path / default_log_file
    log_path.parent.mkdir(parents=True, exist_ok=True)

    stream_handler = logging.StreamHandler()
    for log_filter in shared_filters:
        stream_handler.addFilter(log_filter)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    for log_filter in shared_filters:
        file_handler.addFilter(log_filter)

    if fmt == "json":
        formatter: logging.Formatter = JsonFormatter()
    else:
        formatter = TextFormatter(
            fmt="%(asctime)s %(levelname)s %(name)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    stream_handler.setFormatter(formatter)
    file_handler.setFormatter(formatter)

    root.handlers = [stream_handler, file_handler]
    root.setLevel(level)
