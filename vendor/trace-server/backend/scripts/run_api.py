"""API 启动入口：uvicorn，地址/端口由 config（.env）控制。"""
import sys
from pathlib import Path

import uvicorn

# 让 backend 根目录可导入（api/db 包位于 backend 下）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if __name__ == "__main__":
    from config import HOST, PORT

    uvicorn.run(
        "api.main:app",
        host=HOST,
        port=PORT,
    )
