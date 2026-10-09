"""Tests covering the authentication-error / reconnect-loop interaction.

These tests document two important, pre-existing characteristics of
`Client.reconnect_loop` that are NOT addressed by the on_fatal_error fix in
`Worker`:

1. An authentication failure during token refresh is swallowed by the loop's
   own try/except and retried forever with exponential backoff; it never
   triggers `on_fatal_error` and never stops itself.
2. `Client.stop_reconnect()` can only reliably cancel-and-await the
   background task when called from the same asyncio event loop that is
   running it. If called from a different loop, cancellation is skipped.
"""

from __future__ import annotations

import asyncio

import pytest

from temporallib.client import Client, Options


class AlwaysFailingTemporalClient:
    """Stand-in client whose count_workflows() always raises, simulating a
    permanently broken/expired credential."""

    def __init__(self):
        self.rpc_metadata = {}

    async def count_workflows(self):
        raise PermissionError("invalid credentials")


@pytest.mark.asyncio
async def test_auth_failure_during_refresh_retries_forever_without_stopping():
    """An auth error inside _reconnect() must not stop the reconnect loop or
    require on_fatal_error; it should be retried indefinitely."""
    Client._client = AlwaysFailingTemporalClient()
    Client._client_opts = Options(host="test", namespace="default")
    Client._is_stop_token_refresh = False
    Client._initial_backoff = 0.01
    Client._max_backoff = 0.02
    Client._token_refresh_interval = 1800

    task = asyncio.create_task(Client.reconnect_loop())
    Client._reconnect_task = task
    try:
        # Give it several retry cycles worth of time.
        await asyncio.sleep(0.2)

        # The loop must still be running: an auth failure alone does not
        # stop it, and nothing calls on_fatal_error for it.
        assert not task.done()
        assert Client._is_stop_token_refresh is False
    finally:
        # Explicitly stopping is the only way to end it.
        await Client.stop_reconnect()
        assert task.done()
        Client._initial_backoff = 60
        Client._max_backoff = 600


@pytest.mark.asyncio
async def test_stop_reconnect_actually_cancels_task_same_loop():
    """Sanity check: when called from the same loop as the task, stop_reconnect
    cancels and awaits it, leaving no dangling task."""
    Client._client = AlwaysFailingTemporalClient()
    Client._client_opts = Options(host="test", namespace="default")
    Client._is_stop_token_refresh = False
    Client._initial_backoff = 0.01
    Client._max_backoff = 0.02
    Client._token_refresh_interval = 1800

    task = asyncio.create_task(Client.reconnect_loop())
    Client._reconnect_task = task
    await asyncio.sleep(0.05)

    await Client.stop_reconnect()

    assert task.done()
    assert Client._reconnect_task is None
    assert Client._is_stop_token_refresh is True

    Client._initial_backoff = 60
    Client._max_backoff = 600


def test_stop_reconnect_from_different_event_loop_does_not_cancel_task():
    """Known limitation: if the reconnect task is running on a different
    event loop than the one stop_reconnect() is awaited from (e.g. because
    Client.connect() and the fatal-error handling run on separate loops),
    _cancel_reconnect_task cannot cancel or await it and simply clears the
    reference, leaving the original task running until it next checks
    `_is_stop_token_refresh` itself."""

    async def start_task_on_its_own_loop():
        Client._client = AlwaysFailingTemporalClient()
        Client._client_opts = Options(host="test", namespace="default")
        Client._is_stop_token_refresh = False
        Client._initial_backoff = 0.01
        Client._max_backoff = 0.02
        Client._token_refresh_interval = 1800
        Client._reconnect_task = asyncio.create_task(Client.reconnect_loop())
        # Let it start running.
        await asyncio.sleep(0.05)

    async def call_stop_reconnect_on_a_new_loop():
        await Client.stop_reconnect()

    loop_a = asyncio.new_event_loop()
    try:
        loop_a.run_until_complete(start_task_on_its_own_loop())
        leaked_task = Client._reconnect_task
        assert leaked_task is not None and not leaked_task.done()

        loop_b = asyncio.new_event_loop()
        try:
            loop_b.run_until_complete(call_stop_reconnect_on_a_new_loop())
        finally:
            loop_b.close()

        # The flag is set and the class reference is cleared...
        assert Client._is_stop_token_refresh is True
        assert Client._reconnect_task is None
        # ...but the original task, still owned by loop_a, was never
        # cancelled or awaited by stop_reconnect().
        assert not leaked_task.done()

        # Clean up the leaked task on its owning loop so it doesn't linger.
        leaked_task.cancel()
        loop_a.run_until_complete(asyncio.gather(leaked_task, return_exceptions=True))
    finally:
        loop_a.close()
        Client._initial_backoff = 60
        Client._max_backoff = 600
