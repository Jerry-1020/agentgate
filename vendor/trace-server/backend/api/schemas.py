"""Pydantic 响应模型：把数据库 snake_case 字段转成前端 camelCase。"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ConfigOut(BaseModel):
    storageBackend: str


class ProjectOut(BaseModel):
    id: str
    name: str
    description: str | None = None


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class ErrorInfoOut(BaseModel):
    errorType: str | None = None
    errorCode: str | None = None
    errorCategory: str | None = None
    message: str | None = None
    stackTrace: str | None = None


class TraceOut(BaseModel):
    id: str
    projectId: str
    sessionId: str | None = None
    name: str | None = None
    agentName: str | None = None
    input: Any | None = None
    output: Any | None = None
    durationMs: int | None = None
    totalTokens: int | None = None
    promptTokens: int | None = None
    completionTokens: int | None = None
    reactStepCount: int | None = None
    toolCount: int | None = None
    spanCount: int | None = None
    status: str
    errorInfo: ErrorInfoOut | None = None
    startedAt: str | None = None


class SpanOut(BaseModel):
    id: str
    eventId: str | None = None
    traceId: str
    parentSpanId: str | None = None
    name: str
    spanType: str
    input: Any | None = None
    output: Any | None = None
    durationMs: int | None = None
    model: str | None = None
    toolName: str | None = None
    status: str
    errorInfo: ErrorInfoOut | None = None
    startedAt: str | None = None


class LlmRequestOut(BaseModel):
    eventId: str
    spanId: str | None = None
    model: str | None = None
    input: Any | None = None
    output: Any | None = None
    status: str | None = None
    errorInfo: ErrorInfoOut | None = None
    startedAt: str | None = None


class ObservationOut(BaseModel):
    id: str
    spanId: str | None = None
    model: str | None = None
    promptTokens: int | None = None
    completionTokens: int | None = None
    input: Any | None = None
    output: Any | None = None


class TraceNodeOut(BaseModel):
    span: SpanOut | None = None
    children: list[TraceNodeOut] = Field(default_factory=list)


class TraceListOut(BaseModel):
    items: list[TraceOut]
    total: int
    page: int
    page_size: int


class LlmRequestsOut(BaseModel):
    items: list[LlmRequestOut]


class TraceDetailOut(BaseModel):
    trace: TraceOut
    spans: list[SpanOut]
    observations: list[ObservationOut]


class TraceTreeOut(BaseModel):
    trace: TraceOut
    tree: list[TraceNodeOut]
