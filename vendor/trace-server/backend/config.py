"""服务端集中配置：从 trace_server/.env / 环境变量读取，无硬编码默认值。

所有可配置项：
- STORAGE_BACKEND : database | file
- DATABASE_URL    : SQLAlchemy async URL（database 后端）
- DATA_FILE       : SDK 直写 JSONL 文件目录（file 后端，只读）
- HOST / PORT     : 服务监听地址

配置文件位于 trace_server/.env（后端 + 前端共用），本文件在 backend/ 下。
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# trace_server 根目录 = backend 的上一级
SERVER_ROOT = Path(__file__).resolve().parent.parent
# 加载 trace_server/.env（存在时），环境变量优先（load_dotenv 默认不覆盖已存在变量）
_ENV_FILE = SERVER_ROOT / ".env"
load_dotenv(_ENV_FILE, override=False)

DEFAULT_STORAGE_BACKEND = "database"
STORAGE_BACKENDS = ("database", "file")

# 存储后端
STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", DEFAULT_STORAGE_BACKEND)
if STORAGE_BACKEND not in STORAGE_BACKENDS:
    raise RuntimeError(
        f"STORAGE_BACKEND 无效: {STORAGE_BACKEND!r}，可选 {STORAGE_BACKENDS}"
    )

# 数据库 URL（database 后端必需）
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if STORAGE_BACKEND == "database" and not DATABASE_URL:
    raise RuntimeError(
        "未配置 DATABASE_URL：请在 trace_server/.env 中设置数据库连接，"
        "例如 postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/trace_db"
    )

# SDK 直写 JSONL 文件目录（file 后端使用，只读）
DATA_FILE = os.getenv("DATA_FILE", "trace_data")

# 服务监听
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))

# 若 DATA_FILE 为相对路径，则相对 trace_server/ 根目录解析
if not os.path.isabs(DATA_FILE):
    DATA_FILE = str(SERVER_ROOT / DATA_FILE)
