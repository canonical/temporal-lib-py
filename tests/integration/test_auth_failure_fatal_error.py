"""Integration test: a real, server-enforced PERMISSION_DENIED encountered
mid-poll (simulating a revoked/expired credential) must be treated as FATAL
by the SDK and trigger Worker's on_fatal_error -- even while a long-running
activity is in flight.

This spins up:
  1. A real ephemeral Temporal dev server
     (``temporalio.testing.WorkflowEnvironment``).
  2. A local gRPC proxy (see ``grpc_auth_proxy.py``) in front of it that
     transparently forwards every call, except it rejects calls whose
     ``authorization`` header matches a configured "revoked" value with a
     genuine ``PERMISSION_DENIED`` -- exactly like a real auth-enforcing
     server would for an invalid/expired credential.
  3. A real ``temporallib`` ``Worker``/``Client`` pointed at the proxy, with
     ``AuthHeaderProvider.get_headers`` patched to flip from a valid to an
     invalid header value on demand (no real IdP needed).

This test is inevitably long (3-4 minutes) due to timeouts defined within the
Temporal Rust core that cannot be overridden via Python.
"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import timedelta
from typing import AsyncIterator, List

import pytest
from temporalio import activity, workflow
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner

from temporallib.auth.auth import AuthHeaderProvider, AuthOptions, GoogleAuthOptions
from temporallib.client import Client, Options
from temporallib.worker import Worker

from .grpc_auth_proxy import AuthEnforcingProxy

VALID_AUTH_HEADER = "Bearer valid-dummy-token"
REVOKED_AUTH_HEADER = "Bearer revoked-dummy-token"

# The activity must comfortably outlast FATAL_ERROR_WAIT_TIMEOUT_SECONDS so
# it is still in flight (and gets torn down) when the fatal error fires.
ACTIVITY_DURATION_SECONDS = 170
TOKEN_REFRESH_INTERVAL_SECONDS = 2
FATAL_ERROR_WAIT_TIMEOUT_SECONDS = 150
# Upper bound for the full graceful worker.shutdown() that follows. This is what
# turns a hung worker into a clear test failure instead of an indefinite hang.
GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS = 240


@activity.defn
async def long_running_activity(total_seconds: int) -> str:
    """Dummy activity that heartbeats once a second so the test can observe
    it get cancelled when the worker tears down after a fatal error."""
    for i in range(total_seconds):
        activity.heartbeat(f"heartbeat {i + 1}/{total_seconds}")
        await asyncio.sleep(1)
    return "activity completed normally (fatal error was NOT triggered)"


@workflow.defn
class LongRunningWorkflow:
    @workflow.run
    async def run(self, total_seconds: int) -> str:
        return await workflow.execute_activity(
            long_running_activity,
            total_seconds,
            start_to_close_timeout=timedelta(seconds=total_seconds + 30),
            heartbeat_timeout=timedelta(seconds=10),
        )


class _AuthState:
    """Toggled mid-test to simulate a revoked credential."""

    corrupted = False


def _make_patched_get_headers(auth_state: _AuthState):
    """Replaces the real (network-calling) get_headers() entirely, so this
    test needs no real IdP/candid/google connectivity."""

    def _patched_get_headers(self: AuthHeaderProvider):
        return {
            "authorization": (
                REVOKED_AUTH_HEADER if auth_state.corrupted else VALID_AUTH_HEADER
            )
        }

    return _patched_get_headers


@asynccontextmanager
async def _running_proxy(backend_target: str) -> AsyncIterator[AuthEnforcingProxy]:
    """Starts the auth-enforcing proxy and guarantees it is stopped on exit,
    even if the test body raises."""
    proxy = AuthEnforcingProxy(backend_target)
    proxy.start()
    try:
        yield proxy
    finally:
        proxy.stop()


@asynccontextmanager
async def _running_worker(worker: Worker) -> AsyncIterator[asyncio.Task]:
    """Runs the worker in a background task and tears it down with a full
    graceful worker.shutdown() on exit (not just cancellation), bounded by
    GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS so a regression that leaves the worker
    hung shows up as a clear test failure rather than hanging forever."""
    run_task = asyncio.create_task(worker.run())
    try:
        yield run_task
    finally:
        try:
            await asyncio.wait_for(
                worker.shutdown(), timeout=GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS
            )
        finally:
            if not run_task.done():
                run_task.cancel()
            await asyncio.gather(run_task, return_exceptions=True)


async def _assert_reconnect_loop_stopped_itself() -> None:
    """Prove that Worker's on_fatal_error wrapper itself (not some later/outer
    cleanup) is what stopped the Client reconnect loop. The wrapper runs the
    app callback first (which sets fatal_error_event) and only then stops the
    reconnect loop, so poll briefly for that to happen rather than asserting
    on the wrapper's internal race with our own event."""

    def _reconnect_task_cleared() -> bool:
        return Client._reconnect_task is None or Client._reconnect_task.done()

    async def _wait_for_reconnect_cleared():
        while not _reconnect_task_cleared():
            await asyncio.sleep(0.1)

    try:
        await asyncio.wait_for(_wait_for_reconnect_cleared(), timeout=10)
    except asyncio.TimeoutError:
        pytest.fail(
            "Worker's on_fatal_error wrapper should have stopped the Client "
            "reconnect loop itself, before any outer test/cleanup code calls "
            "Client.stop_reconnect()"
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_permission_denied_during_poll_triggers_on_fatal_error(monkeypatch):
    task_queue = "integration-auth-failure-check"

    async with await WorkflowEnvironment.start_local() as env:
        backend_target = env.client.service_client.config.target_host
        namespace = env.client.namespace

        async with AsyncExitStack() as stack:
            proxy = await stack.enter_async_context(_running_proxy(backend_target))
            # Always stop the reconnect loop at the very end, regardless of
            # whether on_fatal_error's own cleanup already did so.
            stack.push_async_callback(Client.stop_reconnect)

            auth_state = _AuthState()
            monkeypatch.setattr(
                AuthHeaderProvider,
                "get_headers",
                _make_patched_get_headers(auth_state),
            )

            options = Options(
                host=proxy.target,
                queue=task_queue,
                namespace=namespace,
                auth=AuthOptions(
                    provider="google",
                    config=GoogleAuthOptions(
                        project_id="dummy-project",
                        private_key_id="dummy-key-id",
                        private_key="dummy-private-key",
                        client_email="dummy@example.com",
                        client_id="dummy-client-id",
                    ),
                ),
            )
            # Bypass the field's lower-bound validation (assignment is not
            # validated) so the test doesn't wait for the production minimum.
            options.token_refresh_interval = TOKEN_REFRESH_INTERVAL_SECONDS

            fatal_error_event = asyncio.Event()
            captured_exceptions: List[BaseException] = []

            # Define a custom on_fatal_error callback for the worker, which
            # should be executed after a fatal error occurs and before the
            # client disconnect and worker shutdown.
            async def on_fatal_error(exc: BaseException) -> None:
                captured_exceptions.append(exc)
                fatal_error_event.set()

            client = await Client.connect(options)
            worker = Worker(
                client,
                task_queue=task_queue,
                workflows=[LongRunningWorkflow],
                activities=[long_running_activity],
                workflow_runner=UnsandboxedWorkflowRunner(),
                on_fatal_error=on_fatal_error,
            )

            run_task = await stack.enter_async_context(_running_worker(worker))

            await asyncio.sleep(1)
            assert not run_task.done(), "worker should still be polling normally"

            handle = await client.start_workflow(
                LongRunningWorkflow.run,
                ACTIVITY_DURATION_SECONDS,
                id="auth-failure-check",
                task_queue=task_queue,
            )

            # Let the activity actually start and heartbeat at least once
            # before pulling the rug out from under the credential.
            await asyncio.sleep(3)

            # Simulate credential revocation: the proxy now rejects any call
            # carrying the "revoked" header with a genuine PERMISSION_DENIED,
            # exactly like a real auth-enforcing server would.
            proxy.deny(REVOKED_AUTH_HEADER)
            auth_state.corrupted = True

            await asyncio.wait_for(
                fatal_error_event.wait(), timeout=FATAL_ERROR_WAIT_TIMEOUT_SECONDS
            )
            assert captured_exceptions, "on_fatal_error should have fired"

            await _assert_reconnect_loop_stopped_itself()

            # The activity should have been cancelled rather than completing
            # normally.
            with pytest.raises(Exception):
                await asyncio.wait_for(handle.result(), timeout=10)
