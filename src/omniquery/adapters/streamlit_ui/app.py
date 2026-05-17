"""Streamlit driving adapter — chat, schema explorer, and EDA report.

This module is loaded by ``streamlit run`` (see ``runner.py``). It
wires the same container used by the CLI and the FastAPI adapter, so
the UI shares LLM, cache, governance, and persistence singletons with
every other entry point.

Heavy / optional imports (``streamlit``, ``pandas``) live at the top
of the module because Streamlit always invokes it from its own
sub-process — they will be installed via the ``[ui]`` extra.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import pandas as pd
import streamlit as st

from omniquery.adapters.streamlit_ui.state import (
    KEY_CONNECTION_URL,
    KEY_HISTORY,
    KEY_LANGUAGE,
    KEY_MAX_ROWS,
    KEY_THREAD_ID,
    UiQueryRecord,
    ensure_defaults,
)
from omniquery.config import get_settings
from omniquery.domain.entities.eda_query import EdaQuery
from omniquery.infrastructure.container import get_container

# ---------------------------------------------------------------------------
# Page configuration — must be the first Streamlit call.
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="OmniQuery Explorer",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

ensure_defaults(st.session_state)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _apply_runtime_overrides(language: str, provider: str | None) -> None:
    """Push UI choices onto the env BEFORE the container is built.

    Settings cache themselves on first access (``@lru_cache(maxsize=1)``),
    so changing the env after a previous run requires busting the
    cache. We also clear the container cache for the same reason.
    """
    os.environ["LLM_LANGUAGE"] = language
    if provider:
        os.environ["LLM_PROVIDER"] = provider
    get_settings.cache_clear()
    get_container.cache_clear()


def _run_async(coro):
    """Drive an async call from Streamlit's synchronous scriptpath.

    We allocate a fresh event loop per call so successive widget
    interactions are independent — Streamlit re-runs the script on
    every UI tick and a stale loop would leak DB connections.
    """
    return asyncio.run(coro)


def _format_sql(sql: str) -> str:
    """Render SQL inside a syntax-highlighted block."""
    return f"```sql\n{sql}\n```"


# ---------------------------------------------------------------------------
# Sidebar — connection + LLM controls.
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("🔍 OmniQuery Explorer")
    st.caption("Agentic EDA over relational databases")

    st.divider()
    st.subheader("Connection")
    connection_url = st.text_input(
        "Database URL",
        value=st.session_state[KEY_CONNECTION_URL]
        or os.getenv("DATABASE_URL", ""),
        type="password",
        help="SQLAlchemy async URL, e.g. "
        "`postgresql+asyncpg://user:pwd@host/db` "
        "or `sqlite+aiosqlite:///./data.db`.",
    )
    st.session_state[KEY_CONNECTION_URL] = connection_url

    max_rows = st.number_input(
        "Max rows per query",
        min_value=1,
        max_value=10_000,
        value=st.session_state[KEY_MAX_ROWS],
        step=50,
    )
    st.session_state[KEY_MAX_ROWS] = int(max_rows)

    st.divider()
    st.subheader("LLM")
    provider_default = os.getenv("LLM_PROVIDER", "ollama")
    provider = st.selectbox(
        "Provider",
        options=["ollama", "openai", "anthropic", "bedrock", "vertex"],
        index=["ollama", "openai", "anthropic", "bedrock", "vertex"].index(
            provider_default if provider_default in {
                "ollama", "openai", "anthropic", "bedrock", "vertex"
            } else "ollama"
        ),
    )
    language = st.selectbox(
        "Language",
        options=["auto", "en", "es"],
        index=["auto", "en", "es"].index(st.session_state[KEY_LANGUAGE]),
        help="Output language for reports + DB summaries. "
        "Generated SQL is always plain SQL.",
    )
    st.session_state[KEY_LANGUAGE] = language

    st.divider()
    st.subheader("Conversation")
    thread_id = st.text_input(
        "Thread id",
        value=st.session_state[KEY_THREAD_ID],
        help="Reuse the same id across questions to keep agent context "
        "(requires `MEMORY_ENABLED=true`).",
    )
    st.session_state[KEY_THREAD_ID] = thread_id
    if st.button("🆕 New conversation", use_container_width=True):
        from omniquery.adapters.streamlit_ui.state import default_thread_id

        st.session_state[KEY_THREAD_ID] = default_thread_id()
        st.session_state[KEY_HISTORY] = []
        st.rerun()

    st.divider()
    st.caption("OmniQuery Explorer · MIT License")


# Apply runtime overrides before any container access below.
_apply_runtime_overrides(language=language, provider=provider)


# ---------------------------------------------------------------------------
# Header + tab layout.
# ---------------------------------------------------------------------------

st.title("OmniQuery Explorer")
st.markdown(
    "Ask your database questions in **natural language** — safe SQL, real rows, "
    "and a structured analytical report."
)

tab_ask, tab_explore, tab_schema, tab_history = st.tabs(
    ["💬 Ask", "🧭 Explore", "🗂️ Schema", "📜 History"]
)


# ---------------------------------------------------------------------------
# Tab: Ask — single-question flow.
# ---------------------------------------------------------------------------

with tab_ask:
    st.subheader("Single-question EDA")

    if not connection_url:
        st.warning(
            "Set a Database URL in the sidebar to enable the assistant.",
            icon="🔌",
        )
    else:
        with st.form("ask_form", clear_on_submit=False):
            question = st.text_area(
                "Question",
                placeholder=(
                    "e.g. Which 5 customers have spent the most this year?"
                ),
                height=100,
            )
            submit = st.form_submit_button(
                "🚀 Run query", use_container_width=True, type="primary"
            )

        if submit and question.strip():
            container = get_container()
            use_case = container.eda_use_case(connection_url)
            query = EdaQuery(
                question=question.strip(),
                connection_url=connection_url,
                max_rows=int(max_rows),
            )
            with st.spinner("Analysing — schema → SQL → execute → report…"):
                result = _run_async(use_case.run_eda(query))

            record = UiQueryRecord(
                question=question.strip(),
                generated_sql=result.generated_sql or "",
                row_count=result.row_count,
                report=result.report or "",
                error=result.error or "",
                rows=result.raw_data,
            )
            history = list(st.session_state[KEY_HISTORY])
            history.append(record)
            st.session_state[KEY_HISTORY] = history

            if record.error:
                st.error(record.error, icon="❌")
            else:
                col_sql, col_meta = st.columns([3, 1])
                with col_sql:
                    st.markdown("#### Generated SQL")
                    st.code(record.generated_sql, language="sql")
                with col_meta:
                    st.metric("Rows", f"{record.row_count:,}")

                if record.rows:
                    df = pd.DataFrame(record.rows)
                    st.markdown("#### Results")
                    st.dataframe(df, use_container_width=True, hide_index=True)
                    csv = df.to_csv(index=False).encode("utf-8")
                    st.download_button(
                        "⬇️  Download CSV",
                        data=csv,
                        file_name="omniquery_results.csv",
                        mime="text/csv",
                    )

                if record.report:
                    st.markdown("#### Analytical report")
                    st.markdown(record.report)


# ---------------------------------------------------------------------------
# Tab: Explore — full multi-agent pass with proposed questions.
# ---------------------------------------------------------------------------

with tab_explore:
    st.subheader("Explore the database (multi-agent)")
    if not connection_url:
        st.info("Set a Database URL in the sidebar to explore.", icon="ℹ️")
    else:
        if st.button("🧠 Run exploration", type="primary"):
            container = get_container()
            graph = container.eda_session_graph(connection_url)
            with st.spinner("Profiling + ranking + proposing…"):
                questions, scored, summary = _run_async(
                    graph.run_explore(connection_url, int(max_rows))
                )

            if summary:
                st.markdown("#### Database summary")
                st.info(summary)

            if scored:
                st.markdown("#### Top-ranked tables")
                df = pd.DataFrame(
                    [
                        {
                            "Table": s.table_name,
                            "Score": round(s.score, 3),
                            "Rows": s.row_count,
                            "Centrality": round(s.centrality, 3),
                            "Reasons": " · ".join(s.reasons[:3]),
                        }
                        for s in scored[:15]
                    ]
                )
                st.dataframe(df, use_container_width=True, hide_index=True)

            if questions:
                st.markdown("#### Proposed EDA questions")
                for q in questions:
                    st.markdown(
                        f"- **[{q.difficulty} · {q.category}]** {q.question} "
                        f"_(tables: `{', '.join(q.relevant_tables) or '—'}`)_"
                    )


# ---------------------------------------------------------------------------
# Tab: Schema — flat table + columns view.
# ---------------------------------------------------------------------------


async def _load_schema(url: str) -> Any:
    """Use the same DatabasePort the rest of the pipeline trusts."""
    from omniquery.infrastructure.db.adapter_factory import resolve_db_adapter

    adapter = resolve_db_adapter(url)
    return await adapter.get_schema(url)


with tab_schema:
    st.subheader("Schema browser")
    if not connection_url:
        st.info("Set a Database URL in the sidebar to inspect the schema.", icon="ℹ️")
    elif st.button("🔄 Refresh schema"):
        with st.spinner("Reflecting…"):
            db_schema = _run_async(_load_schema(connection_url))
        st.caption(
            f"Engine: `{db_schema.engine.value}` · DB: `{db_schema.db_name}` · "
            f"{len(db_schema.tables)} table(s)"
        )
        for table in db_schema.tables:
            with st.expander(f"📋 {table.name}"):
                df = pd.DataFrame(
                    [
                        {
                            "Column": c.name,
                            "Type": c.sql_type,
                            "Nullable": "✓" if c.nullable else "—",
                            "PK": "🔑" if c.is_primary_key else "",
                            "FK →": (
                                f"{c.foreign_key.referred_table}."
                                f"{c.foreign_key.referred_column}"
                                if c.foreign_key
                                else ""
                            ),
                        }
                        for c in table.columns
                    ]
                )
                st.dataframe(df, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Tab: History — questions asked this session.
# ---------------------------------------------------------------------------

with tab_history:
    st.subheader("Session history")
    history: list[UiQueryRecord] = st.session_state[KEY_HISTORY]
    if not history:
        st.caption("No queries in this session yet.")
    else:
        for i, rec in enumerate(reversed(history), start=1):
            ordinal = len(history) - i + 1
            with st.expander(f"#{ordinal} · {rec.question[:80]}"):
                if rec.error:
                    st.error(rec.error, icon="❌")
                else:
                    st.code(rec.generated_sql, language="sql")
                    st.caption(f"{rec.row_count:,} rows")
                    if rec.report:
                        st.markdown(rec.report)
