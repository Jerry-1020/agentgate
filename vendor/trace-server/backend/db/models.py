"""ORM 模型：与 db/schema.sql 的 5 张表一一对应（Repository Pattern 的领域模型层）。

字段类型采用 PostgreSQL 方言（JSONB、UUID），SQLite 下由 SQLAlchemy 自动降级兼容。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Session(Base):
    __tablename__ = "sessions"

    # id 用 VARCHAR：session_id 语义与 langfuse 一致（可为任意字符串，如 sess-xxx）
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE")
    )
    name: Mapped[str | None] = mapped_column(String(255))
    user_id: Mapped[str | None] = mapped_column(String(255))
    metadata_json: Mapped[dict | None] = Column("metadata", JSONB)
    trace_count: Mapped[int] = mapped_column(Integer, server_default="0")
    total_tokens: Mapped[int] = mapped_column(BigInteger, server_default="0")
    total_duration_ms: Mapped[int] = mapped_column(BigInteger, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (Index("idx_sessions_project", "project_id", "created_at"),)


class Trace(Base):
    __tablename__ = "traces"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True)
    event_id: Mapped[str] = mapped_column(UUID(as_uuid=True), unique=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE")
    )
    session_id: Mapped[str | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="SET NULL")
    )
    name: Mapped[str | None] = mapped_column(String(255))
    agent_name: Mapped[str | None] = mapped_column(String(255))
    input: Mapped[dict | None] = mapped_column(JSONB)
    output: Mapped[dict | None] = mapped_column(JSONB)
    duration_ms: Mapped[int | None] = mapped_column(BigInteger)
    react_step_count: Mapped[int] = mapped_column(Integer, server_default="0")
    tool_count: Mapped[int] = mapped_column(Integer, server_default="0")
    span_count: Mapped[int] = mapped_column(Integer, server_default="0")
    status: Mapped[str] = mapped_column(String(20), server_default="success")
    error_info: Mapped[dict | None] = mapped_column(JSONB)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_traces_project_time", "project_id", "created_at"),
        Index("idx_traces_session", "session_id"),
    )


class Span(Base):
    __tablename__ = "spans"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True)
    event_id: Mapped[str] = mapped_column(UUID(as_uuid=True), unique=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE")
    )
    trace_id: Mapped[str] = mapped_column(
        ForeignKey("traces.id", ondelete="CASCADE")
    )
    parent_span_id: Mapped[str | None] = mapped_column(UUID(as_uuid=True))
    name: Mapped[str] = mapped_column(String(255))
    span_type: Mapped[str] = mapped_column(String(20))
    input: Mapped[dict | None] = mapped_column(JSONB)
    output: Mapped[dict | None] = mapped_column(JSONB)
    duration_ms: Mapped[int | None] = mapped_column(BigInteger)
    model: Mapped[str | None] = mapped_column(String(255))
    tool_name: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), server_default="success")
    error_info: Mapped[dict | None] = mapped_column(JSONB)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_spans_trace", "trace_id"),
        Index("idx_spans_parent", "parent_span_id"),
        Index("idx_spans_project_time", "project_id", "created_at"),
    )


class Observation(Base):
    __tablename__ = "observations"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True)
    event_id: Mapped[str] = mapped_column(UUID(as_uuid=True), unique=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE")
    )
    trace_id: Mapped[str] = mapped_column(
        ForeignKey("traces.id", ondelete="CASCADE")
    )
    span_id: Mapped[str | None] = mapped_column(
        ForeignKey("spans.id", ondelete="CASCADE")
    )
    model: Mapped[str | None] = mapped_column(String(255))
    prompt_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    completion_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    input: Mapped[dict | None] = mapped_column(JSONB)
    output: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("idx_observations_span", "span_id"),
        Index("idx_observations_trace", "trace_id"),
    )


class LlmRequest(Base):
    """真实 LLM 请求（中间件拦截，event_id 关联 llm span）。

    与 db/schema.sql 的 llm_requests 表对应：event_id 主键（幂等），
    input/output 为真实请求/响应 payload。
    """

    __tablename__ = "llm_requests"

    event_id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True)
    id: Mapped[str] = mapped_column(UUID(as_uuid=True))
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE")
    )
    trace_id: Mapped[str] = mapped_column(
        ForeignKey("traces.id", ondelete="CASCADE")
    )
    span_id: Mapped[str | None] = mapped_column(
        ForeignKey("spans.id", ondelete="CASCADE")
    )
    model: Mapped[str | None] = mapped_column(String(256))
    input: Mapped[dict] = mapped_column(JSONB)
    output: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), server_default="success")
    error_info: Mapped[dict | None] = mapped_column(JSONB)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_llm_requests_trace", "trace_id"),
        Index("idx_llm_requests_span", "span_id"),
    )
