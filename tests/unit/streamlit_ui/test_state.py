"""Unit tests for streamlit_ui.state.

We do NOT import the main ``app.py`` module here because it pulls in
streamlit + pandas (heavy optional extras). The state helpers stay
dependency-light so the CI default job can validate them without
the ``[ui]`` extra installed.
"""

from __future__ import annotations

from omniquery.adapters.streamlit_ui.state import (
    KEY_CONNECTION_URL,
    KEY_HISTORY,
    KEY_LANGUAGE,
    KEY_MAX_ROWS,
    KEY_THREAD_ID,
    UiQueryRecord,
    default_thread_id,
    ensure_defaults,
)


def test_default_thread_id_format():
    tid = default_thread_id()
    assert tid.startswith("ui-")
    assert len(tid) == len("ui-") + 8


def test_default_thread_id_is_unique():
    # Two calls must produce different ids — otherwise resuming a
    # previous session would silently overwrite history.
    assert default_thread_id() != default_thread_id()


def test_ensure_defaults_populates_all_keys():
    state: dict = {}
    ensure_defaults(state)
    for key in (
        KEY_HISTORY,
        KEY_THREAD_ID,
        KEY_CONNECTION_URL,
        KEY_MAX_ROWS,
        KEY_LANGUAGE,
    ):
        assert key in state


def test_ensure_defaults_is_idempotent():
    state: dict = {KEY_LANGUAGE: "es"}
    ensure_defaults(state)
    # Already-set keys must NOT be overwritten — that would clobber
    # user preferences across Streamlit reruns.
    assert state[KEY_LANGUAGE] == "es"


def test_query_record_defaults_empty_lists():
    rec = UiQueryRecord(question="?")
    assert rec.rows == []
    assert rec.row_count == 0
    assert rec.error == ""
