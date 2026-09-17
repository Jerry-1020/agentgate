"""Live model connection. There is no offline/mock fallback in the service."""
import json
import os

import httpx


class LiveModel:
    def __init__(self):
        self.url = os.environ.get("BANK_MODEL_BASE_URL", "").rstrip("/")
        self.key = os.environ.get("BANK_MODEL_API_KEY", "")
        self.name = os.environ.get("BANK_MODEL_NAME", "")
        if not all((self.url, self.key, self.name)):
            raise ValueError("BANK_MODEL_BASE_URL, BANK_MODEL_API_KEY and BANK_MODEL_NAME are required")

    def complete(self, messages, evidence, tools=None, json_mode=False):
        payload = {"model": self.name, "messages": messages, "temperature": 0,
                   "max_tokens": 1600, "stream": False}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        with evidence.span("model.complete", "llm", inputs=payload, model=self.name) as span:
            try:
                with httpx.Client(timeout=60, follow_redirects=False, trust_env=False) as client:
                    response = client.post(self.url + "/chat/completions", json=payload,
                                           headers={"Authorization": f"Bearer {self.key}"})
                    response.raise_for_status()
                    body = response.json()
                message = body["choices"][0]["message"]
                if not isinstance(message, dict) or not (message.get("content") or message.get("tool_calls")):
                    raise ValueError("empty model response")
            except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
                # Provider response bodies may echo secrets. Do not persist them.
                raise RuntimeError("model request failed: " + type(exc).__name__) from None
            evidence.collector.bump_llm()
            usage = body.get("usage", {})
            evidence.collector.add_observation(span_id=span["meta"]["span_id"], model=self.name,
                prompt_tokens=usage.get("prompt_tokens", 0), completion_tokens=usage.get("completion_tokens", 0))
            evidence.collector.record_llm_request(event_id=span["meta"]["event_id"], span_id=span["meta"]["span_id"],
                model=self.name, input=payload, output=message, started_at=span["meta"]["started_at"])
            span["output"] = message
            # Only protocol fields are carried into the next model request.
            return {k: v for k, v in message.items() if k in {"role", "content", "tool_calls"}}

    def structured(self, prompt, messages, evidence):
        message = self.complete([{"role": "system", "content": prompt}, *messages], evidence, json_mode=True)
        try:
            value = json.loads(message["content"])
        except (ValueError, KeyError, TypeError):
            raise ValueError("model returned invalid structured data") from None
        if not isinstance(value, dict):
            raise ValueError("model JSON must be an object")
        return value
