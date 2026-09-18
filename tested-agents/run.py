"""Start only the local tested-Agent service, never the customer factory scripts."""
import argparse
import os
import shlex
from pathlib import Path

import uvicorn


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-env", type=Path, help="external env file; never copied into repository")
    parser.add_argument("--use-agentgate-model", action="store_true", help="explicitly reuse configured Judge connection for the tested Agent")
    parser.add_argument("--port", type=int, default=8107)
    args = parser.parse_args()
    if args.model_env:
        for line in args.model_env.read_text().splitlines():
            line = line.strip().removeprefix("export ")
            if not line or line.startswith("#"):
                continue
            key, separator, value = line.partition("=")
            if separator and key.startswith(("BANK_MODEL_", "AGENTGATE_JUDGE_")):
                parts = shlex.split(value, comments=True)
                if len(parts) == 1:
                    os.environ[key] = parts[0]
    if args.use_agentgate_model:
        for target, source in (("BANK_MODEL_BASE_URL", "AGENTGATE_JUDGE_BASE_URL"),
                               ("BANK_MODEL_API_KEY", "AGENTGATE_JUDGE_API_KEY"),
                               ("BANK_MODEL_NAME", "AGENTGATE_JUDGE_MODEL_ID")):
            if target not in os.environ and source in os.environ:
                os.environ[target] = os.environ[source]
    os.environ.setdefault("BANK_RUNTIME_DIR", str(Path(__file__).resolve().parents[1] / "runtime" / "bank-agents"))
    uvicorn.run("bank_agents.app:create_app", factory=True, host="127.0.0.1", port=args.port)
