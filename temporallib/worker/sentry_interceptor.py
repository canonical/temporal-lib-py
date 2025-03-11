"""Temporal client worker Sentry interceptor."""

from dataclasses import asdict, is_dataclass
from typing import Any, Optional, Type, Union
from pydantic_settings import BaseSettings
from pydantic import validator
from temporalio import activity, workflow
from temporalio.worker import (
    ActivityInboundInterceptor,
    ExecuteActivityInput,
    ExecuteWorkflowInput,
    Interceptor,
    WorkflowInboundInterceptor,
    WorkflowInterceptorClassInput,
)

with workflow.unsafe.imports_passed_through():
    from sentry_sdk import Hub, capture_exception, set_context, set_tag


class SentryOptions(BaseSettings):
    """
    Defines the parameters for configuring Sentry error reporting.
    """
    dsn: Optional[str]
    release: Optional[str]
    environment: Optional[str]
    sample_rate: Optional[float] = 1.0
    redact_params: Optional[bool] = False

    class Config:
        env_prefix = "TEMPORAL_SENTRY_"

    @validator('sample_rate', pre=True, always=True)
    def validate_sample_rate(cls, v):
        return float(v) if v is not None else None

    @validator('redact_params', pre=True, always=True)
    def validate_redact_params(cls, v):
        return v if v is not None else (os.getenv("TEMPORAL_SENTRY_REDACT_PARAMS", "").lower() == "true")

def _set_common_workflow_tags(info: Union[workflow.Info, activity.Info]):
    set_tag("temporal.workflow.type", info.workflow_type)
    set_tag("temporal.workflow.id", info.workflow_id)


class _SentryActivityInboundInterceptor(ActivityInboundInterceptor):
    async def execute_activity(self, input: ExecuteActivityInput) -> Any:
        # https://docs.sentry.io/platforms/python/troubleshooting/#addressing-concurrency-issues
        with Hub(Hub.current):
            set_tag("temporal.execution_type", "activity")
            set_tag("module", input.fn.__module__ + "." + input.fn.__qualname__)

            activity_info = activity.info()
            _set_common_workflow_tags(activity_info)
            set_tag("temporal.activity.id", activity_info.activity_id)
            set_tag("temporal.activity.type", activity_info.activity_type)
            set_tag("temporal.activity.task_queue", activity_info.task_queue)
            set_tag("temporal.workflow.namespace", activity_info.workflow_namespace)
            set_tag("temporal.workflow.run_id", activity_info.workflow_run_id)
            try:
                return await super().execute_activity(input)
            except Exception as e:
                if len(input.args) == 1 and is_dataclass(input.args[0]):
                    set_context("temporal.activity.input", asdict(input.args[0]))
                set_context("temporal.activity.info", activity.info().__dict__)
                capture_exception()
                raise e


class _SentryWorkflowInterceptor(WorkflowInboundInterceptor):
    async def execute_workflow(self, input: ExecuteWorkflowInput) -> Any:
        # https://docs.sentry.io/platforms/python/troubleshooting/#addressing-concurrency-issues
        with Hub(Hub.current):
            set_tag("temporal.execution_type", "workflow")
            set_tag("module", input.run_fn.__module__ + "." + input.run_fn.__qualname__)
            workflow_info = workflow.info()
            _set_common_workflow_tags(workflow_info)
            set_tag("temporal.workflow.task_queue", workflow_info.task_queue)
            set_tag("temporal.workflow.namespace", workflow_info.namespace)
            set_tag("temporal.workflow.run_id", workflow_info.run_id)
            try:
                return await super().execute_workflow(input)
            except Exception as e:
                if len(input.args) == 1 and is_dataclass(input.args[0]):
                    set_context("temporal.workflow.input", asdict(input.args[0]))
                set_context("temporal.workflow.info", workflow.info().__dict__)

                if not workflow.unsafe.is_replaying():
                    with workflow.unsafe.sandbox_unrestricted():
                        capture_exception()
                raise e


class SentryInterceptor(Interceptor):
    """Temporal Interceptor class which will report workflow & activity exceptions to Sentry."""

    def intercept_activity(
        self, next: ActivityInboundInterceptor
    ) -> ActivityInboundInterceptor:
        """Implement :py:meth:`temporalio.worker.Interceptor.intercept_activity`."""
        return _SentryActivityInboundInterceptor(super().intercept_activity(next))

    def workflow_interceptor_class(
        self, input: WorkflowInterceptorClassInput
    ) -> Optional[Type[WorkflowInboundInterceptor]]:
        """Retrieve the workflow interceptor class based on the provided input."""
        return _SentryWorkflowInterceptor

def group_exceptions(event, hint):
    """Returns a Sentry event with a custom fingerprint for grouping."""
    # Override the default grouping behavior
    if "exception" not in event:
        return event
    if "values" not in event["exception"]:
        return event

    # Default values
    workflow_name = "unknown_workflow"
    namespace = "unknown_namespace"
    activity_type = "unknown_activity"

    # Extract workflow_type and namespace from breadcrumbs (if available)
    breadcrumbs = event.get("breadcrumbs", {}).get("values", [])
    for breadcrumb in breadcrumbs:
        if breadcrumb.get("category") == "temporalio.activity":
            temporal_data = breadcrumb.get("data", {}).get("temporal_activity", {})
            workflow_name = temporal_data.get("workflow_type", workflow_name)
            namespace = temporal_data.get("namespace", namespace)
            activity_type = temporal_data.get("activity_type", activity_type)
            break  # Stop at the first found occurrence

    # Set a consistent fingerprint
    if "exception" in event:
        exc_type = event["exception"]["values"][0]["type"]
        event["fingerprint"] = [namespace, workflow_name, activity_type, exc_type]

    return event

def redact_params(event, hint):
    """Returns a Sentry event with all variables redacted."""
    # Redact parameters from captured events
    if "exception" not in event:
        return event
    if "values" not in event["exception"]:
        return event

    for exc in event["exception"]["values"]:
        if "stacktrace" not in exc:
            continue
        for frame in exc["stacktrace"]["frames"]:
            # Filter out specific parameter keys
            if "vars" in frame:
                frame["vars"] = {key: "REDACTED" for key in frame["vars"]}

    return event

def create_before_send(redact_params_enabled=False):
    """
    Returns a `before_send` function that applies `group_exceptions` 
    and conditionally applies `redact_params` based on `redact_params`.
    """
    def before_send(event, hint):
        event = group_exceptions(event, hint)

        if redact_params_enabled:
            event = redact_params(event, hint)

        return event

    return before_send
