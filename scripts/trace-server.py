"""Compose the untouched upstream query API with AgentGate's HTTP ingestion."""

import os
from pathlib import Path

import uvicorn
from api.main import app

from agentgate.integrations.observability.trace_ingestion import install_ingestion

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8210)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    install_ingestion(app, Path(os.environ["DATA_FILE"]), os.environ["TRACE_REPORT_TOKEN"])
    uvicorn.run(app, host=args.host, port=args.port)
