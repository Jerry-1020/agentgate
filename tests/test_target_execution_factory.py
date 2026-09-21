"""Target composition loads only selected settings and owns no remote resources."""

from contextlib import ExitStack
from unittest.mock import Mock

import pytest
from test_celery_dispatcher import target as demo_target

from agentgate.domain import TargetSnapshot
from agentgate.integrations.targets import execution_factory as factory


def target_snapshot(adapter_type, adapter_version="1"):
    values = demo_target().model_dump(exclude={"content_sha256"})
    values.update(
        adapter_type=adapter_type,
        adapter_version=adapter_version,
        invocation_config={"arrange_type": "base"},
    )
    return TargetSnapshot(**values)


def configure_inbank(monkeypatch, adapter_type):
    monkeypatch.setenv("AGENTGATE_INBANK_CREATE_BASE_URL", "http://bank.invalid")
    prefix = "CHATABC" if adapter_type == "inbank_chatabc" else "YUNXIA"
    for name in ("HEALTH", "POD_API", "DELETE"):
        monkeypatch.setenv(f"AGENTGATE_INBANK_{prefix}_{name}_BASE_URL", "http://bank.invalid")
    if prefix == "YUNXIA":
        monkeypatch.setenv("AGENTGATE_INBANK_YUNXIA_AGENT_NAMESPACE", "test")
        monkeypatch.setenv("AGENTGATE_INBANK_YUNXIA_TEST_CUSTOMER_PREFIX", "test-customer")


@pytest.mark.parametrize(
    "adapter_class,resolver",
    [
        (factory.DemoLoanTargetAdapter, None),
        (factory.LocalBankAdapter, factory.resolve_local_bank_trace),
        (factory.InbankChatABCTargetAdapter, factory.resolve_chatabc_trace),
        (factory.InbankYunxiaTargetAdapter, factory.resolve_yunxia_trace),
    ],
)
def test_create_selects_components_without_starting_target(monkeypatch, adapter_class, resolver):
    for name in ("load_chatabc_settings", "load_yunxia_settings"):
        loader = getattr(factory, name)
        monkeypatch.setattr(factory, name, Mock(wraps=loader))
    if adapter_class.adapter_type.startswith("inbank_"):
        configure_inbank(monkeypatch, adapter_class.adapter_type)
    with ExitStack() as resources:
        adapter, actual_resolver = factory.TargetExecutionFactory.create(
            target_snapshot(adapter_class.adapter_type), resources
        )
        assert isinstance(adapter, adapter_class)
        if resolver is not None:
            assert actual_resolver is resolver
        else:
            assert actual_resolver == adapter.capture.resolve
        if adapter_class.adapter_type.startswith("inbank_"):
            assert adapter.pod_lifecycle["create"] == "not_attempted"
    assert factory.load_chatabc_settings.call_count == (
        adapter_class.adapter_type == "inbank_chatabc"
    )
    assert factory.load_yunxia_settings.call_count == (
        adapter_class.adapter_type == "inbank_yunxia"
    )


@pytest.mark.parametrize("adapter_type", ["inbank_chatabc", "inbank_yunxia"])
@pytest.mark.parametrize("invalid_version", [False, True])
def test_caller_scope_cleans_adapter_even_on_version_error(
    monkeypatch, adapter_type, invalid_version
):
    configure_inbank(monkeypatch, adapter_type)
    adapter_class = (
        factory.InbankChatABCTargetAdapter
        if adapter_type == "inbank_chatabc"
        else factory.InbankYunxiaTargetAdapter
    )
    close = Mock()
    monkeypatch.setattr(adapter_class, "close", close)
    target = target_snapshot(adapter_type, "unsupported" if invalid_version else "1")
    if invalid_version:
        with pytest.raises(ValueError, match="adapter_version"), ExitStack() as resources:
            factory.TargetExecutionFactory.create(target, resources)
    else:
        with ExitStack() as resources:
            first, _ = factory.TargetExecutionFactory.create(target, resources)
            close.assert_not_called()
        with ExitStack() as resources:
            second, _ = factory.TargetExecutionFactory.create(target, resources)
            assert second is not first
    assert close.call_count == (1 if invalid_version else 2)


def test_unknown_adapter_does_not_fall_back_to_demo():
    with pytest.raises(ValueError, match="does not support"), ExitStack() as resources:
        factory.TargetExecutionFactory.create(target_snapshot("unknown"), resources)
