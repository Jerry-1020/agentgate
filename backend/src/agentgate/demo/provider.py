from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any
from urllib.request import Request, urlopen


class AgentProvider(ABC):
    name: str

    @abstractmethod
    def choose_action(self, request: dict[str, Any], version: str) -> dict[str, Any]: ...


class DeterministicProvider(AgentProvider):
    name = "deterministic"

    def choose_action(self, request: dict[str, Any], version: str) -> dict[str, Any]:
        skill = request.get("skill", "loan_approval")
        if skill != "loan_approval":
            return {"tool": skill, "arguments": request}
        risk = request.get("risk", "low")
        if version == "loan-agent-v1-risky" and risk == "high":
            return {"tool": "approve_loan", "arguments": {"approved": True, "human_review": False}}
        if risk == "high":
            return {"tool": "request_human_review", "arguments": {"approved": False, "human_review": True}}
        return {"tool": "approve_loan", "arguments": {"approved": True, "human_review": False}}


class OpenAICompatibleProvider(AgentProvider):
    """Optional provider. No endpoint or credential is required for the demo path."""

    name = "openai-compatible"

    def __init__(self, endpoint: str, model: str, api_key: str | None = None) -> None:
        self.endpoint, self.model, self.api_key = endpoint, model, api_key

    def choose_action(self, request: dict[str, Any], version: str) -> dict[str, Any]:
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": json.dumps({"request": request, "version": version})}],
            "response_format": {"type": "json_object"},
        }).encode()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        with urlopen(Request(self.endpoint, data=body, headers=headers), timeout=30) as response:
            payload = json.load(response)
        return json.loads(payload["choices"][0]["message"]["content"])
