"""SQLAlchemy ORM models for the internal persistence DB.

The internal DB stores sessions, queries, and reports — anything the
analyst might want to revisit later. It is *separate* from the analysed
database; by default it is a local SQLite file (``.tmp/omniquery.db``)
and can be pointed at a Postgres URL in production via
``PERSIST_DATABASE_URL``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class SessionRecord(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    connection_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    db_engine: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )

    queries: Mapped[list[QueryRecord]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class QueryRecord(Base):
    __tablename__ = "queries"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    question: Mapped[str] = mapped_column(Text)
    generated_sql: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    error: Mapped[str] = mapped_column(Text, default="")
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )

    session: Mapped[SessionRecord] = relationship(back_populates="queries")
    report: Mapped[ReportRecord | None] = relationship(
        back_populates="query",
        cascade="all, delete-orphan",
        uselist=False,
    )


class ReportRecord(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    query_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("queries.id", ondelete="CASCADE"), unique=True
    )
    markdown: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    query: Mapped[QueryRecord] = relationship(back_populates="report")
