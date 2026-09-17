"""AgentGate FastAPI application construction and ASGI entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from agentgate.integrations.credentials.encryption import ApiKeyEncryptor
from agentgate.integrations.job_dispatchers import JobDispatcher
from agentgate.server.dependencies import build_dependencies
from agentgate.server.user_context import UserInfo, set_user_info
from agentgate.server.routes import (
    catalogs,
    comparisons,
    credentials,
    datasets,
    evaluators,
    lineage,
    optimizer,
    results,
    runs,
    skill_analysis,
    system,
    telemetry,
)


def create_app(
    database_path: str | Path | None = None,
    dispatcher: JobDispatcher | None = None,
    api_key_encryptor: ApiKeyEncryptor | None = None,
) -> FastAPI:
    """Build one AgentGate HTTP application with isolated dependencies."""

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
                user_team_id=request.headers.get("user_team_id", "python_auto_fill"),
                user_id=request.headers.get("user_id", "python_auto_fill"),
                user_name=request.headers.get("user_name", "python_auto_fill"),
            )
            set_user_info(info)
            print(
                f"UserContext: user_team_id={info.user_team_id}, "
                f"user_id={info.user_id}, user_name={info.user_name}"
            )
            return await call_next(request)

    application.add_middleware(UserContextMiddleware)

    application.state.dependencies = dependencies
    application.include_router(system.router)
    application.include_router(datasets.router)
    application.include_router(catalogs.router)
    application.include_router(credentials.router)
    application.include_router(evaluators.router)
    application.include_router(runs.router)
    application.include_router(results.router)
    application.include_router(comparisons.router)
    application.include_router(lineage.router)
    application.include_router(skill_analysis.router)
    application.include_router(optimizer.router)
    application.include_router(telemetry.router)
    return application


load_dotenv()

app = create_app()
