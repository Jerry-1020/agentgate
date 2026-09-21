"""AgentGate FastAPI application construction and ASGI entry point."""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from agentgate.integrations.credentials.encryption import ApiKeyEncryptor
from agentgate.integrations.job_dispatchers import JobDispatcher
from agentgate.server.dependencies import build_dependencies
from agentgate.server.errors import _safe_message
from agentgate.server.logging_config import setup_logging
from agentgate.server.routes import (
    agent_platform,
    bank_targets,
    catalogs,
    comparisons,
    credentials,
    datasets,
    evaluation_tasks,
    evaluators,
    lineage,
    optimizer,
    results,
    runs,
    skill_analysis,
    stability,
    system,
    telemetry,
)
from agentgate.server.user_context import UserInfo, reset_user_info, set_user_info

LOGGER = logging.getLogger(__name__)

SKIP_ENVELOPE_PATHS = {"/v1/traces"}


class ResponseEnvelopeMiddleware(BaseHTTPMiddleware):
    """Wrap all JSON responses in the unified {code, message, data} envelope."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        if request.url.path in SKIP_ENVELOPE_PATHS:
            return response
        if response.status_code == 204:
            return response
        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            return response

        body_chunks = []
        async for chunk in response.body_iterator:
            body_chunks.append(chunk)
        body = b"".join(body_chunks)
        if not body:
            return response

        try:
            original = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return Response(
                content=body,
                status_code=response.status_code,
                media_type="application/json",
            )

        if (
            isinstance(original, dict)
            and set(original.keys()) == {"code", "message", "data"}
        ):
            return response

        if (
            isinstance(original, dict)
            and "detail" in original
            and "data" not in original
        ):
            detail = original["detail"]
            if isinstance(detail, str):
                envelope = {"code": "1", "message": detail, "data": None}
            elif isinstance(detail, list):
                message = "; ".join(
                    item.get("msg", str(item))
                    if isinstance(item, dict)
                    else str(item)
                    for item in detail
                )
                envelope = {"code": "1", "message": message, "data": detail}
            else:
                message = (
                    detail.get("message", str(detail))
                    if isinstance(detail, dict)
                    else str(detail)
                )
                envelope = {"code": "1", "message": message, "data": detail}
        else:
            envelope = {"code": "0", "message": "success", "data": original}

        headers = {
            k: v
            for k, v in response.headers.items()
            if k.lower() not in ("content-length", "content-type")
        }
        return JSONResponse(
            content=envelope,
            status_code=response.status_code,
            headers=headers,
        )


def create_app(
    database_path: str | Path | None = None,
    dispatcher: JobDispatcher | None = None,
    api_key_encryptor: ApiKeyEncryptor | None = None,
) -> FastAPI:
    """Build one AgentGate HTTP application with isolated dependencies."""

    setup_logging()

    dependencies = build_dependencies(
        database_path,
        dispatcher,
        api_key_encryptor,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        try:
            dependencies.runs.fail_stale_runs()
            yield
        finally:
            dependencies.close()

    application = FastAPI(
        title="AgentGate",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    class UserContextMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            info = UserInfo(
                user_team_id=request.headers.get("user_team_id", ""),
                user_id=request.headers.get("user_id") or "anonymous",
                user_name=request.headers.get("user_name") or "匿名用户",
            )
            token = set_user_info(info)
            try:
                return await call_next(request)
            finally:
                reset_user_info(token)

    application.add_middleware(UserContextMiddleware)
    application.add_middleware(ResponseEnvelopeMiddleware)

    from agentgate.application.agent_platform_evaluation import submit_platform_evaluation

    application.state.submit_agent_platform_evaluation = partial(
        submit_platform_evaluation,
        repository=dependencies.repository,
        evaluators=dependencies.evaluators,
        credentials=dependencies.api_keys,
        dispatcher=dependencies.dispatcher,
    )
    application.state.dependencies = dependencies
    application.include_router(agent_platform.router)
    application.include_router(system.router)
    application.include_router(bank_targets.router)
    application.include_router(stability.router)
    application.include_router(datasets.router)
    application.include_router(catalogs.router)
    application.include_router(credentials.router)
    application.include_router(evaluators.router)
    application.include_router(evaluation_tasks.router)
    application.include_router(runs.router)
    application.include_router(results.router)
    application.include_router(comparisons.router)
    application.include_router(lineage.router)
    application.include_router(skill_analysis.router)
    application.include_router(optimizer.router)
    application.include_router(telemetry.router)

    @application.exception_handler(Exception)
    async def handle_unexpected_exception(request: Request, exc: Exception) -> JSONResponse:
        LOGGER.exception(
            "Unhandled error on %s %s",
            request.method,
            request.url.path,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": _safe_message(exc)},
        )

    return application


app = create_app()
