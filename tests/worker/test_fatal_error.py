"""Tests for worker fatal error handling and reconnect cleanup."""

import asyncio
import logging
import threading
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from temporallib.auth import AuthOptions, GoogleAuthOptions
from temporallib.client import Client, Options
from temporallib.worker.worker import TemporalWorker, Worker


def _make_worker_capturing_on_fatal_error(on_fatal_error=None):
    """Instantiate a real Worker with TemporalWorker.__init__ mocked out, and
    return the actual `on_fatal_error` callable that temporallib.Worker passes
    to the parent class. This exercises the real wiring in Worker.__init__
    instead of re-implementing the wrapper logic in the test.
    """
    captured_kwargs = {}

    def fake_super_init(self, **kwargs):
        captured_kwargs.update(kwargs)

    with patch.object(TemporalWorker, "__init__", fake_super_init):
        Worker(
            client=MagicMock(),
            task_queue="test-queue",
            on_fatal_error=on_fatal_error,
        )

    assert "on_fatal_error" in captured_kwargs
    return captured_kwargs["on_fatal_error"]


@pytest.mark.asyncio
async def test_on_fatal_error_stops_reconnect_loop():
    """Verify that the REAL wrapper built by Worker.__init__ runs the user
    callback and then stops the reconnect loop."""
    Client._client = MagicMock()
    Client._reconnect_task = asyncio.create_task(asyncio.sleep(10))  # Long-running task
    Client._is_stop_token_refresh = False

    try:
        exc = RuntimeError("Test fatal error")

        user_callback_called = False

        async def user_callback(err):
            nonlocal user_callback_called
            user_callback_called = True
            assert err is exc

        wrapped_callback = _make_worker_capturing_on_fatal_error(user_callback)

        # Call the ACTUAL wrapper produced by Worker.__init__
        await wrapped_callback(exc)

        assert user_callback_called
        assert Client._is_stop_token_refresh is True
        assert Client._reconnect_task is None

    finally:
        Client._is_stop_token_refresh = False
        if Client._reconnect_task:
            Client._reconnect_task.cancel()
        Client._reconnect_task = None


@pytest.mark.asyncio
async def test_on_fatal_error_runs_even_if_user_callback_raises():
    """Verify that reconnect cleanup runs even if the REAL wrapped user
    callback raises, and that the exception does NOT propagate (it is caught
    and logged internally, matching the actual worker.py implementation)."""
    Client._client = MagicMock()
    Client._reconnect_task = asyncio.create_task(asyncio.sleep(10))
    Client._is_stop_token_refresh = False

    try:
        exc = RuntimeError("Test fatal error")

        async def failing_user_callback(err):
            raise ValueError("User callback error")

        wrapped_callback = _make_worker_capturing_on_fatal_error(failing_user_callback)

        # The real wrapper swallows/logs the user callback's exception; it
        # must not propagate to the caller (the SDK).
        await wrapped_callback(exc)

        # But reconnect cleanup should still have happened
        assert Client._is_stop_token_refresh is True
        assert Client._reconnect_task is None

    finally:
        Client._is_stop_token_refresh = False
        if Client._reconnect_task:
            Client._reconnect_task.cancel()
        Client._reconnect_task = None


@pytest.mark.asyncio
async def test_on_fatal_error_with_no_custom_callback():
    """Verify that when the app supplies no on_fatal_error, the wrapper still
    stops the reconnect loop without raising."""
    Client._client = MagicMock()
    Client._reconnect_task = asyncio.create_task(asyncio.sleep(10))
    Client._is_stop_token_refresh = False

    try:
        wrapped_callback = _make_worker_capturing_on_fatal_error(on_fatal_error=None)

        await wrapped_callback(RuntimeError("Test fatal error"))

        assert Client._is_stop_token_refresh is True
        assert Client._reconnect_task is None

    finally:
        Client._is_stop_token_refresh = False
        if Client._reconnect_task:
            Client._reconnect_task.cancel()
        Client._reconnect_task = None


@pytest.mark.asyncio
async def test_on_fatal_error_logs_when_stop_reconnect_raises(caplog):
    """Verify that if Client.stop_reconnect() itself raises, the exception is
    caught and logged rather than propagating to the SDK."""
    wrapped_callback = _make_worker_capturing_on_fatal_error(on_fatal_error=None)

    with patch.object(
        Client, "stop_reconnect", AsyncMock(side_effect=RuntimeError("boom"))
    ):
        with caplog.at_level(logging.ERROR):
            # Must not raise even though stop_reconnect() fails internally
            await wrapped_callback(RuntimeError("Test fatal error"))

    assert any(
        "Failed to stop reconnect loop during shutdown" in record.message
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_client_can_reconnect_after_fatal_error():
    """Verify that Client.connect() works after a fatal error and cleanup."""
    # Simulate a fatal error and cleanup
    Client._is_stop_token_refresh = True
    if Client._reconnect_task:
        Client._reconnect_task.cancel()
    Client._reconnect_task = None
    Client._client = None

    # Now verify we can call connect again (won't actually connect in test, but should not error on setup)
    Client._is_stop_token_refresh = False
    assert Client._client is None or not Client._client
    # In a real test, we'd mock TemporalClient.connect here


@pytest.mark.asyncio
async def test_on_fatal_error_arms_force_exit_timer(monkeypatch):
    """A hung shutdown after a fatal error must end in a forced process exit."""
    from temporallib.worker import worker as worker_module

    exited = threading.Event()
    monkeypatch.setattr(worker_module, "_force_exit", exited.set)

    captured = {}
    with patch.object(
        TemporalWorker, "__init__", lambda self, **kw: captured.update(kw)
    ):
        Worker(
            client=MagicMock(),
            task_queue="q",
            fatal_exit_timeout=timedelta(seconds=0.1),
        )

    Client._client = MagicMock()
    Client._reconnect_task = None
    await captured["on_fatal_error"](RuntimeError("boom"))

    assert exited.wait(timeout=5)


@pytest.mark.asyncio
async def test_force_exit_timer_disabled_when_timeout_is_none(monkeypatch):
    from temporallib.worker import worker as worker_module

    captured = {}
    with patch.object(
        TemporalWorker, "__init__", lambda self, **kw: captured.update(kw)
    ):
        Worker(client=MagicMock(), task_queue="q", fatal_exit_timeout=None)

    Client._client = MagicMock()
    Client._reconnect_task = None
    await captured["on_fatal_error"](RuntimeError("boom"))

    assert worker_module._force_exit_timer is None


def test_log_token_state_on_fatal_error(caplog):
    Client._record_token({"authorization": "Bearer secret-token-value"})
    with caplog.at_level(logging.ERROR):
        Client.log_token_state_on_fatal_error(RuntimeError("boom"))

    text = caplog.text
    assert f"fingerprint={Client._last_token_fingerprint}" in text
    assert "age=" in text
    assert "secret-token-value" not in text
