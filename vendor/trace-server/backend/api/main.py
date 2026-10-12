"""FastAPI 应用入口：路由注册 + CORS + 前端静态托管 + 生命周期。"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config import STORAGE_BACKEND
from db.connection import close_engine, init_engine
from .routes import projects, traces
from .schemas import ConfigOut

# 前端构建产物目录（web 构建后生成于 web/dist，由本服务统一托管）
# 本文件位于 backend/api/main.py，web/dist 在 trace_server/web/dist
STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "web" / "dist"
INDEX_HTML = STATIC_DIR / "index.html"


@asynccontextmanager
async def lifespan(app: FastAPI):
    if STORAGE_BACKEND == "database":
        init_engine()
    yield
    if STORAGE_BACKEND == "database":
        await close_engine()


app = FastAPI(title="Trace Monitor API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

api_prefix = "/api/v1"


@app.get("/api/v1/config", response_model=ConfigOut)
async def get_config():
    """返回当前存储后端模式（file/database），供前端据此显示/隐藏功能。"""
    return ConfigOut(storageBackend=STORAGE_BACKEND)


app.include_router(projects.router, prefix=api_prefix, tags=["projects"])
app.include_router(traces.router, prefix=api_prefix, tags=["traces"])


@app.get("/health")
async def health():
    return {"status": "ok"}


# 托管前端构建产物（API 与页面同进程提供）
if INDEX_HTML.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        """SPA 路由回退：非 API 路径一律返回 index.html（前端路由接管）。"""
        # 若命中真实静态文件（如 favicon.svg），直接返回文件
        candidate = STATIC_DIR / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(INDEX_HTML)
