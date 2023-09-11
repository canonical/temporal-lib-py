from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Sequence, Callable, Optional, Type
import concurrent.futures

from datetime import timedelta
from temporalio.worker import Worker as TemporalWorker
from temporalio.worker import SharedStateManager, WorkflowRunner
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner
from temporalio.worker._workflow_instance import UnsandboxedWorkflowRunner
from temporalio.client import Interceptor, OutboundInterceptor
from collections import defaultdict

from temporallib.client import Client
from temporallib.worker.sentry_interceptor import (
    SentryInterceptor,
    SentryOptions,
    redact_params,
)
import sentry_sdk


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
        task_queue: str,
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
    ):
        if interceptors is None:
            interceptors = []

        if worker_opt:
            if worker_opt.sentry:
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

        super().__init__(
            client=client,
            task_queue=task_queue,
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
        )
