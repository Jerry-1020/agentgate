from __future__ import annotations

from itertools import combinations

import pytest

from agentgate.integrations.model_providers.environment import (
    API_KEY_ENV,
    BASE_URL_ENV,
    MODEL_ID_ENV,
    ORIGINAL_DIGEST_HEX_ENV,
    PROVIDER_ID_ENV,
    SESSION_ID_ENV,
    SIGNATURE_HEX_ENV,
    TRANSPORT_ENV,
    ConfiguredJudgeModel,
    load_judge_model_from_environment,
)
from agentgate.integrations.model_providers.openai_compatible import (
    OpenAICompatibleModelClient,
)

COMPLETE_ENVIRONMENT = {
    PROVIDER_ID_ENV: "company-llm",
    BASE_URL_ENV: "https://models.example/v1",
    API_KEY_ENV: "top-secret",
    MODEL_ID_ENV: "judge-model",
}
ENVIRONMENT_NAMES = tuple(COMPLETE_ENVIRONMENT)
PARTIAL_ENVIRONMENTS = [
    {name: COMPLETE_ENVIRONMENT[name] for name in selected}
    for size in range(1, len(ENVIRONMENT_NAMES))
    for selected in combinations(ENVIRONMENT_NAMES, size)
]

SDK_EXTRA_ENVIRONMENT = {
    SIGNATURE_HEX_ENV: "sig-value",
    ORIGINAL_DIGEST_HEX_ENV: "digest-value",
    SESSION_ID_ENV: "session-value",
}
COMPLETE_SDK_ENVIRONMENT = {
    **COMPLETE_ENVIRONMENT,
    TRANSPORT_ENV: "sdk",
    **SDK_EXTRA_ENVIRONMENT,
}


def test_returns_none_when_judge_environment_is_absent() -> None:
    assert load_judge_model_from_environment({}) is None


def test_builds_safe_configured_judge_model() -> None:
    environment = dict(COMPLETE_ENVIRONMENT)

    configured = load_judge_model_from_environment(environment)

    assert isinstance(configured, ConfiguredJudgeModel)
    assert configured.provider_id == "company-llm"
    assert configured.model_id == "judge-model"
    assert configured.credential_ref == "env:AGENTGATE_JUDGE_API_KEY"
    assert configured.client.provider_id == "company-llm"
    assert configured.client.base_url == "https://models.example/v1"
    assert "top-secret" not in repr(configured)
    assert environment == COMPLETE_ENVIRONMENT
    configured.client.close()


@pytest.mark.parametrize("environment", PARTIAL_ENVIRONMENTS)
def test_rejects_every_partial_environment(
    environment: dict[str, str],
) -> None:
    missing = sorted(set(ENVIRONMENT_NAMES).difference(environment))

    with pytest.raises(ValueError, match="incomplete Judge environment") as raised:
        load_judge_model_from_environment(environment)

    assert all(name in str(raised.value) for name in missing)
    assert "top-secret" not in str(raised.value)


@pytest.mark.parametrize("name", ENVIRONMENT_NAMES)
def test_rejects_present_but_blank_values(name: str) -> None:
    environment = dict(COMPLETE_ENVIRONMENT)
    environment[name] = " "

    with pytest.raises(ValueError, match=name) as raised:
        load_judge_model_from_environment(environment)

    assert "top-secret" not in str(raised.value)


# ---------------------------------------------------------------------------
# Transport switch tests
# ---------------------------------------------------------------------------


def test_defaults_to_api_transport_when_unset() -> None:
    environment = dict(COMPLETE_ENVIRONMENT)

    configured = load_judge_model_from_environment(environment)

    assert isinstance(configured.client, OpenAICompatibleModelClient)
    configured.client.close()


def test_api_transport_builds_openai_compatible_client() -> None:
    environment = {**COMPLETE_ENVIRONMENT, TRANSPORT_ENV: "api"}

    configured = load_judge_model_from_environment(environment)

    assert isinstance(configured.client, OpenAICompatibleModelClient)
    configured.client.close()


def test_sdk_transport_builds_inbank_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "agentgate.integrations.model_providers.inbank_llm.InbankLLMModelClient._build_sdk_client",
        lambda self: object(),
    )
    environment = dict(COMPLETE_SDK_ENVIRONMENT)

    configured = load_judge_model_from_environment(environment)

    from agentgate.integrations.model_providers.inbank_llm import (
        InbankLLMModelClient,
    )

    assert isinstance(configured.client, InbankLLMModelClient)
    assert configured.client.provider_id == "company-llm"
    configured.client.close()


def test_sdk_transport_rejects_missing_extra_variables() -> None:
    environment = {**COMPLETE_ENVIRONMENT, TRANSPORT_ENV: "sdk"}

    with pytest.raises(ValueError, match="incomplete Judge SDK environment") as raised:
        load_judge_model_from_environment(environment)

    assert SIGNATURE_HEX_ENV in str(raised.value)
    assert ORIGINAL_DIGEST_HEX_ENV in str(raised.value)
    assert SESSION_ID_ENV in str(raised.value)
    assert "top-secret" not in str(raised.value)


@pytest.mark.parametrize("name", tuple(SDK_EXTRA_ENVIRONMENT))
def test_sdk_transport_rejects_blank_extra_variables(
    name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "agentgate.integrations.model_providers.inbank_llm.InbankLLMModelClient._build_sdk_client",
        lambda self: object(),
    )
    environment = {**COMPLETE_SDK_ENVIRONMENT}
    environment[name] = " "

    with pytest.raises(ValueError, match=name) as raised:
        load_judge_model_from_environment(environment)

    assert "top-secret" not in str(raised.value)


def test_rejects_invalid_transport_value() -> None:
    environment = {**COMPLETE_ENVIRONMENT, TRANSPORT_ENV: "grpc"}

    with pytest.raises(ValueError, match="must be 'api' or 'sdk'"):
        load_judge_model_from_environment(environment)


def test_api_transport_never_imports_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    """Selecting api must not trigger any abc_llm_sdk import."""

    import sys

    monkeypatch.setitem(sys.modules, "abc_llm_sdk", None)

    environment = {**COMPLETE_ENVIRONMENT, TRANSPORT_ENV: "api"}

    configured = load_judge_model_from_environment(environment)

    assert isinstance(configured.client, OpenAICompatibleModelClient)
    configured.client.close()
