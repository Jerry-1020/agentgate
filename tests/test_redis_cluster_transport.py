from __future__ import annotations

from unittest.mock import MagicMock, sentinel

from kombu.transport import get_transport_cls
from redis.crc import key_slot

from agentgate.integrations.job_dispatchers.celery import REDIS_CLUSTER_TRANSPORT
from agentgate.integrations.job_dispatchers.redis_cluster_transport import (
    Channel,
    PrefixedStrictRedis,
    Transport,
)


def test_cluster_transport_is_loadable_by_fully_qualified_name() -> None:
    assert get_transport_cls(REDIS_CLUSTER_TRANSPORT) is Transport


def test_cluster_transport_exposes_hash_tag_configuration() -> None:
    assert "hash_tag" in Channel.from_transport_options
    assert Transport.driver_type == "rediscluster"
    assert Transport.driver_name == "rediscluster"


def test_lock_node_is_selected_from_the_exact_prefixed_key() -> None:
    client = object.__new__(PrefixedStrictRedis)
    client.global_keyprefix = "{agentgate}"
    client.encoder = MagicMock()
    client.encoder.encode.side_effect = lambda value: value.encode("utf-8")
    client.nodes_manager = MagicMock()
    client.nodes_manager.get_node_from_slot.return_value = sentinel.node

    full_key, node = client.prefixed_key_and_node("unacked_mutex")

    assert full_key == "{agentgate}unacked_mutex"
    assert node is sentinel.node
    client.nodes_manager.get_node_from_slot.assert_called_once_with(
        key_slot(full_key.encode("utf-8"))
    )
