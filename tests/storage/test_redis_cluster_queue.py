"""Exercise Celery delivery through a real Redis Cluster."""

from __future__ import annotations

import os
from threading import Event
from uuid import uuid4

import pytest
from celery.contrib.testing.worker import start_worker
from redis.cluster import RedisCluster

from agentgate.integrations.job_dispatchers.celery import create_celery_app


def test_celery_delivers_through_redis_cluster(monkeypatch) -> None:
    cluster_url = os.getenv("AGENTGATE_REDIS_CLUSTER_TEST_URL")
    if not cluster_url:
        pytest.skip("AGENTGATE_REDIS_CLUSTER_TEST_URL is required")

    hash_tag = "{agentgate-cluster-test}"
    monkeypatch.setenv("AGENTGATE_REDIS_MODE", "cluster")
    monkeypatch.setenv("AGENTGATE_REDIS_URL", cluster_url)
    monkeypatch.setenv("AGENTGATE_REDIS_CLUSTER_HASH_TAG", hash_tag)
    app = create_celery_app()
    delivered = Event()
    received: list[str] = []

    @app.task(name=f"agentgate.cluster_test.{uuid4()}")
    def record_delivery(value: str) -> None:
        received.append(value)
        delivered.set()

    with start_worker(
        app,
        concurrency=1,
        pool="solo",
        perform_ping_check=False,
        loglevel="WARNING",
    ):
        record_delivery.apply_async(args=["cluster-ok"])
        assert delivered.wait(20), "Celery worker did not receive the Cluster task"

    assert received == ["cluster-ok"]

    client = RedisCluster.from_url(cluster_url)
    try:
        keys = list(client.scan_iter(match="*"))
        assert keys
        decoded_keys = [
            key.decode("utf-8") if isinstance(key, bytes) else key for key in keys
        ]
        assert all(key.startswith(hash_tag) for key in decoded_keys)
        client.delete(*keys)
    finally:
        client.close()
