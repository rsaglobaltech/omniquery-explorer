"""initial persistence schema (sessions, queries, reports)

Revision ID: 202605170001
Revises:
Create Date: 2026-05-17

Mirrors infrastructure/persistence/models.py at the time the
persistence layer was introduced (commit b8a9ea9). Future schema
changes should be added as new revision files, never by editing this
one in place.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# Alembic identifiers.
revision: str = "202605170001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # sessions: one row per analyst session against a target DB.
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("connection_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("db_engine", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_sessions_connection_fingerprint",
        "sessions",
        ["connection_fingerprint"],
    )
    op.create_index("ix_sessions_created_at", "sessions", ["created_at"])

    # queries: one row per RunEdaUseCase execution.
    op.create_table(
        "queries",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(length=64),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("generated_sql", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default="pending"
        ),
        sa.Column("error", sa.Text, nullable=False, server_default=""),
        sa.Column("row_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_queries_session_id", "queries", ["session_id"])
    op.create_index("ix_queries_status", "queries", ["status"])
    op.create_index("ix_queries_created_at", "queries", ["created_at"])

    # reports: at most one report per query (unique FK).
    op.create_table(
        "reports",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "query_id",
            sa.String(length=64),
            sa.ForeignKey("queries.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("markdown", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    # Drop in reverse FK order. We rely on the FKs themselves to clean
    # up children when SQLite is in BATCH mode (env.py renders that).
    op.drop_table("reports")
    op.drop_index("ix_queries_created_at", table_name="queries")
    op.drop_index("ix_queries_status", table_name="queries")
    op.drop_index("ix_queries_session_id", table_name="queries")
    op.drop_table("queries")
    op.drop_index("ix_sessions_created_at", table_name="sessions")
    op.drop_index("ix_sessions_connection_fingerprint", table_name="sessions")
    op.drop_table("sessions")
