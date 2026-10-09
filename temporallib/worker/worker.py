from __future__ import annotations

import concurrent.futures
import logging
import os
import threading
from dataclasses import dataclass
from datetime import timedelta
from typing import Awaitable, Callable, Optional, Sequence, Type

import sentry_sdk
from temporalio.client import Interceptor
from temporalio.worker import SharedStateManager
from temporalio.worker import Worker as TemporalWorker
from temporalio.worker import WorkflowRunner
from temporalio.worker._workflow_instance import UnsandboxedWorkflowRunner
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner

from temporallib.client import Client
from temporallib.worker.sentry_interceptor import (
    SentryInterceptor,
    SentryOptions,
    redact_params,
)

logging.basicConfig(level=logging.INFO)

DEFAULT_FATAL_EXIT_TIMEOUT = timedelta(seconds=60)

_force_exit_timer_lock = threading.Lock()
_force_exit_timer: Optional[threading.Timer] = None


def _force_exit() -> None:
    logging.critical(
        "Worker did not shut down in time after a fatal error; forcing process exit"
    )
    try:
        sentry_sdk.flush(timeout=2)
    except Exception:
        pass
    for handler in logging.getLogger().handlers:
        try:
            handler.flush()
        except Exception:
            pass
    os._exit(1)


def _arm_force_exit_timer(timeout: float) -> None:
    """Force the process to exit if graceful shutdown hangs after a fatal error.

    Uses a daemon thread rather than the event loop, so it still fires if the
    loop is wedged, and does not keep a cleanly exiting process alive.
    """
    global _force_exit_timer
    with _force_exit_timer_lock:
        if _force_exit_timer is not None:
            return
        _force_exit_timer = threading.Timer(timeout, _force_exit)
        _force_exit_timer.daemon = True
        _force_exit_timer.start()
    logging.warning("Fatal error force-exit timer armed: forcing exit in %ss", timeout)


@dataclass
class WorkerOptions:
    sentry: SentryOptions = None


class Worker(TemporalWorker):
    """
    A class which wraps the :class:`temporalio.client.Client` class
    """

    def __init__(
        self,
        client: Client,
        task_queue: Optional[str] = None,
        workflows: Sequence[Type] = [],
        activities: Sequence[Callable] = [],
        worker_opt: Optional[WorkerOptions] = None,
        activity_executor: Optional[concurrent.futures.Executor] = None,
        workflow_task_executor: Optional[concurrent.futures.ThreadPoolExecutor] = None,
        workflow_runner: WorkflowRunner = SandboxedWorkflowRunner(),
        unsandboxed_workflow_runner: WorkflowRunner = UnsandboxedWorkflowRunner(),
        interceptors: Sequence[Interceptor] = None,
        build_id: Optional[str] = None,
        identity: Optional[str] = None,
        max_cached_workflows: int = 1000,
        max_concurrent_workflow_tasks: int = 100,
        max_concurrent_activities: int = 100,
        max_concurrent_local_activities: int = 100,
        max_concurrent_workflow_task_polls: int = 5,
        nonsticky_to_sticky_poll_ratio: float = 0.2,
        max_concurrent_activity_task_polls: int = 5,
        no_remote_activities: bool = False,
        sticky_queue_schedule_to_start_timeout: timedelta = timedelta(seconds=10),
        max_heartbeat_throttle_interval: timedelta = timedelta(seconds=60),
        default_heartbeat_throttle_interval: timedelta = timedelta(seconds=30),
        max_activities_per_second: Optional[float] = None,
        max_task_queue_activities_per_second: Optional[float] = None,
        graceful_shutdown_timeout: timedelta = timedelta(),
        shared_state_manager: Optional[SharedStateManager] = None,
        debug_mode: bool = False,
        disable_eager_activity_execution: bool = False,
        on_fatal_error: Optional[Callable[[BaseException], Awaitable[None]]] = None,
        use_worker_versioning: bool = False,
        fatal_exit_timeout: Optional[timedelta] = DEFAULT_FATAL_EXIT_TIMEOUT,
    ):
        if interceptors is None:
            interceptors = []

        self._task_queue = task_queue or os.getenv("TEMPORAL_QUEUE")
        if not self._task_queue:
            raise ValueError(
                "task_queue must be provided either as a parameter or an environment variable."
            )

        if worker_opt:
            if worker_opt.sentry and worker_opt.sentry.dsn:
                interceptors.append(SentryInterceptor())

                before_send = None
                if worker_opt.sentry.redact_params:
                    before_send = redact_params

                sentry_sdk.init(
                    dsn=worker_opt.sentry.dsn,
                    release=worker_opt.sentry.release,
                    environment=worker_opt.sentry.environment,
                    sample_rate=worker_opt.sentry.sample_rate,
                    before_send=before_send,
                )

        _user_on_fatal_error = on_fatal_error

        async def _on_fatal_error_with_cleanup(exc: BaseException) -> None:
            """Run user callback (if any), then stop the reconnect loop.

            If fatal_exit_timeout is set, arm a timer to force the process to exit
            after graceful_shutdown_timeout + fatal_exit_timeout.
            """
            if fatal_exit_timeout is not None:
                _arm_force_exit_timer(
                    (graceful_shutdown_timeout + fatal_exit_timeout).total_seconds()
                )
            Client.log_token_state_on_fatal_error(exc)
            try:
                if _user_on_fatal_error:
                    try:
                        await _user_on_fatal_error(exc)
                    except Exception:
                        logging.exception(
                            "User on_fatal_error callback raised an exception"
                        )
            finally:
                # Always stop the reconnect loop, even if the user callback failed
                try:
                    await Client.stop_reconnect()
                except Exception:
                    logging.exception("Failed to stop reconnect loop during shutdown")

        # Pass the wrapper to the parent Worker class
        on_fatal_error = _on_fatal_error_with_cleanup

        super().__init__(
            client=client,
            task_queue=self._task_queue,
            workflows=workflows,
            activities=activities,
            activity_executor=activity_executor,
            workflow_task_executor=workflow_task_executor,
            workflow_runner=workflow_runner,
            unsandboxed_workflow_runner=unsandboxed_workflow_runner,
            interceptors=interceptors,
            build_id=build_id,
            identity=identity,
            max_cached_workflows=max_cached_workflows,
            max_concurrent_workflow_tasks=max_concurrent_workflow_tasks,
            max_concurrent_activities=max_concurrent_activities,
            max_concurrent_local_activities=max_concurrent_local_activities,
            max_concurrent_workflow_task_polls=max_concurrent_workflow_task_polls,
            nonsticky_to_sticky_poll_ratio=nonsticky_to_sticky_poll_ratio,
            max_concurrent_activity_task_polls=max_concurrent_activity_task_polls,
            no_remote_activities=no_remote_activities,
            sticky_queue_schedule_to_start_timeout=sticky_queue_schedule_to_start_timeout,
            max_heartbeat_throttle_interval=max_heartbeat_throttle_interval,
            default_heartbeat_throttle_interval=default_heartbeat_throttle_interval,
            max_activities_per_second=max_activities_per_second,
            max_task_queue_activities_per_second=max_task_queue_activities_per_second,
            graceful_shutdown_timeout=graceful_shutdown_timeout,
            shared_state_manager=shared_state_manager,
            debug_mode=debug_mode,
            disable_eager_activity_execution=disable_eager_activity_execution,
            on_fatal_error=on_fatal_error,
            use_worker_versioning=use_worker_versioning,
        )
