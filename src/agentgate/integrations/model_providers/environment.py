"""Process-level environment configuration for one POC Judge model."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass

from agentgate.evaluator.judge import JudgeModelClient

from .openai_compatible import OpenAICompatibleModelClient

LOGGER = logging.getLogger(__name__)

PROVIDER_ID_ENV = "AGENTGATE_JUDGE_PROVIDER_ID"
BASE_URL_ENV = "AGENTGATE_JUDGE_BASE_URL"
API_KEY_ENV = "AGENTGATE_JUDGE_API_KEY"
MODEL_ID_ENV = "AGENTGATE_JUDGE_MODEL_ID"
TRANSPORT_ENV = "AGENTGATE_JUDGE_TRANSPORT"
SIGNATURE_HEX_ENV = "AGENTGATE_JUDGE_SIGNATURE_HEX"
ORIGINAL_DIGEST_HEX_ENV = "AGENTGATE_JUDGE_ORIGINAL_DIGEST_HEX"
SESSION_ID_ENV = "AGENTGATE_JUDGE_SESSION_ID"
_REQUIRED_ENVIRONMENT = (
    PROVIDER_ID_ENV,
    BASE_URL_ENV,
    API_KEY_ENV,
    MODEL_ID_ENV,
)
_SDK_EXTRA_ENVIRONMENT = (
    SIGNATURE_HEX_ENV,
    ORIGINAL_DIGEST_HEX_ENV,
    SESSION_ID_ENV,
)
_VALID_TRANSPORTS = frozenset({"api", "sdk"})


def _required_value(environ: Mapping[str, str], name: str) -> str:
    value = environ[name]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonblank string")
    return value.strip()


@dataclass(frozen=True, slots=True)
class ConfiguredJudgeModel:
    """Safe metadata and live client built from Judge environment settings."""

    provider_id: str
    model_id: str
    credential_ref: str
    client: JudgeModelClient


def load_judge_model_from_environment(
    environ: Mapping[str, str] | None = None,
) -> ConfiguredJudgeModel | None:
    """Build one Judge model client, or return None when entirely unconfigured."""

    source = os.environ if environ is None else environ
    present = {name for name in _REQUIRED_ENVIRONMENT if name in source}
    if not present:
        return None
    missing = set(_REQUIRED_ENVIRONMENT).difference(present)
    if missing:
        raise ValueError(
            "incomplete Judge environment; missing: "
            + ", ".join(sorted(missing))
        )

    provider_id = _required_value(source, PROVIDER_ID_ENV)
    base_url = _required_value(source, BASE_URL_ENV)
    api_key = _required_value(source, API_KEY_ENV)
    model_id = _required_value(source, MODEL_ID_ENV)

    transport = source.get(TRANSPORT_ENV, "api").strip().lower()
    if transport not in _VALID_TRANSPORTS:
        raise ValueError(
            f"{TRANSPORT_ENV} must be 'api' or 'sdk', got {transport!r}"
        )

    if transport == "sdk":
        client = _build_sdk_client(
            source,
            provider_id=provider_id,
            base_url=base_url,
            model_id=model_id,
            api_key=api_key,
        )
    else:
        LOGGER.info(
            "Judge model configured: transport=api, provider_id=%s, model_id=%s",
            provider_id,
            model_id,
        )
        client = OpenAICompatibleModelClient(
            provider_id=provider_id,
            base_url=base_url,
            api_key=api_key,
        )

    return ConfiguredJudgeModel(
        provider_id=provider_id,
        model_id=model_id,
        credential_ref=f"env:{API_KEY_ENV}",
        client=client,
    )


def _build_sdk_client(
    source: Mapping[str, str],
    *,
    provider_id: str,
    base_url: str,
    model_id: str,
    api_key: str,
) -> JudgeModelClient:
    """Build an InbankLLMModelClient from SDK-specific environment variables."""

    missing = {
        name for name in _SDK_EXTRA_ENVIRONMENT if name not in source
    }
    if missing:
        raise ValueError(
            "incomplete Judge SDK environment; missing: "
            + ", ".join(sorted(missing))
        )

    signature_hex = _required_value(source, SIGNATURE_HEX_ENV)
    original_digest_hex = _required_value(source, ORIGINAL_DIGEST_HEX_ENV)
    session_id = _required_value(source, SESSION_ID_ENV)

    from .inbank_llm import InbankLLMModelClient

    return InbankLLMModelClient(
        provider_id=provider_id,
        base_url=base_url,
        model_name=model_id,
        api_key=api_key,
        signature_hex=signature_hex,
        original_digest_hex=original_digest_hex,
        session_id=session_id,
    )


__all__ = [
    "API_KEY_ENV",
    "BASE_URL_ENV",
    "MODEL_ID_ENV",
    "ORIGINAL_DIGEST_HEX_ENV",
    "PROVIDER_ID_ENV",
    "SESSION_ID_ENV",
    "SIGNATURE_HEX_ENV",
    "TRANSPORT_ENV",
    "ConfiguredJudgeModel",
    "load_judge_model_from_environment",
]
