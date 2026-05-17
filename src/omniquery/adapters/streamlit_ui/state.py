"""Session state helpers for the Streamlit UI.

Centralises the keys we stash in ``st.session_state`` so typos and
key drift never sneak in. Pure Python — Streamlit is imported lazily
where needed so unit tests can exercise the helpers without
``streamlit`` installed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class UiQueryRecord:
    """One past Q&A in the current Streamlit tab — used by the chat tab."""

    question: str
    generated_sql: str = ""
    row_count: int = 0
    report: str = ""
    error: str = ""
    rows: list[dict[str, Any]] = field(default_factory=list)


def default_thread_id() -> str:
    """Mint a deterministic-shaped thread id for a fresh tab."""
    # Short hex keeps the id readable in logs and copy-paste friendly.
    return f"ui-{uuid.uuid4().hex[:8]}"


# Session-state keys. Centralised as module-level constants so the
# page modules can refer to them without sprinkling string literals.
KEY_HISTORY = "ui.history"
KEY_THREAD_ID = "ui.thread_id"
KEY_CONNECTION_URL = "ui.connection_url"
KEY_MAX_ROWS = "ui.max_rows"
KEY_LANGUAGE = "ui.language"


def ensure_defaults(state: dict[str, Any]) -> None:
    """Populate missing keys with sensible defaults.

    ``state`` is treated as a mapping so we can pass either the real
    ``st.session_state`` (a Mapping-like proxy) or a plain dict in
    unit tests.
    """
    state.setdefault(KEY_HISTORY, [])
    state.setdefault(KEY_THREAD_ID, default_thread_id())
    state.setdefault(KEY_CONNECTION_URL, "")
    state.setdefault(KEY_MAX_ROWS, 500)
    state.setdefault(KEY_LANGUAGE, "auto")
