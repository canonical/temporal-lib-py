from __future__ import annotations

import asyncio
import threading
import time

import pytest

from temporallib.auth import AuthHeaderProvider, AuthOptions, GoogleAuthOptions
from temporallib.client import Client, Options


class FakeTemporalClient:
    def __init__(self):
        self.rpc_metadata = {}
        self.count_workflows_calls = 0

    async def count_workflows(self):
        self.count_workflows_calls += 1


@pytest.mark.asyncio
async def test_reconnect_token_refresh_does_not_block_event_loop(monkeypatch):
    refresh_started = threading.Event()
    heartbeat_ticks = []

    def slow_get_headers(self):
        refresh_started.set()
        time.sleep(0.4)
        return {"authorization": "Bearer refreshed-token"}

    async def heartbeat():
        while not refresh_started.is_set():
            await asyncio.sleep(0.01)

        while refresh_started.is_set():
            heartbeat_ticks.append(time.monotonic())
            await asyncio.sleep(0.05)

    monkeypatch.setattr(AuthHeaderProvider, "get_headers", slow_get_headers)
    Client._client = FakeTemporalClient()
    Client._client_opts = Options(
        host="test",
        namespace="default",
        auth=AuthOptions(
            provider="google",
            config=GoogleAuthOptions(
                project_id="test",
                private_key_id="test",
                private_key="test",
                client_email="test@example.com",
                client_id="test",
            ),
        ),
    )

    heartbeat_task = asyncio.create_task(heartbeat())
    await Client._reconnect()
    refresh_started.clear()
    heartbeat_task.cancel()
    await asyncio.gather(heartbeat_task, return_exceptions=True)

    assert Client._client.rpc_metadata["authorization"] == "Bearer refreshed-token"
    assert Client._client.count_workflows_calls == 1
    assert len(heartbeat_ticks) >= 2
