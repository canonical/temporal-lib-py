"""A transparent gRPC passthrough proxy used by integration tests to inject a
real, server-side PERMISSION_DENIED error into the real temporalio SDK's
poller, without needing any actual auth-enforcing infrastructure.

It works at the raw-bytes level (no knowledge of the Temporal WorkflowService
proto schema is required): every incoming unary RPC, for any method, is
forwarded byte-for-byte to a real backend Temporal server, unless the request
carries the ``authorization`` metadata value configured via :meth:`deny`, in
which case the proxy itself aborts the call with ``PERMISSION_DENIED`` --
just like a real auth-enforcing server would for a revoked/expired
credential.
"""

from __future__ import annotations

import logging
from concurrent import futures
from typing import Optional

import grpc

logger = logging.getLogger(__name__)


def _passthrough(data: bytes) -> bytes:
    """Identity (de)serializer: we never decode messages, only forward the
    raw bytes, so this proxy needs no knowledge of the proto schema."""
    return data


class _PassthroughHandler(grpc.GenericRpcHandler):
    """Routes every RPC, regardless of service/method name, through a single
    handler that forwards raw bytes to the proxy's backend channel, or
    aborts with ``PERMISSION_DENIED`` if the request's ``authorization``
    metadata matches ``proxy.deny_authorization``."""

    def __init__(self, proxy: "AuthEnforcingProxy"):
        self._proxy = proxy

    def service(self, handler_call_details: grpc.HandlerCallDetails):
        method = handler_call_details.method

        def _unary_unary(request_bytes: bytes, context: grpc.ServicerContext):
            metadata = tuple(context.invocation_metadata() or ())
            deny_value = self._proxy.deny_authorization
            if (
                deny_value is not None
                and dict(metadata).get("authorization") == deny_value
            ):
                logger.warning(
                    "AuthEnforcingProxy: rejecting %s with PERMISSION_DENIED "
                    "(simulated revoked credential)",
                    method,
                )
                context.abort(
                    grpc.StatusCode.PERMISSION_DENIED,
                    "Simulated credential revocation by AuthEnforcingProxy",
                )

            backend_call = self._proxy.backend_channel.unary_unary(
                method,
                request_serializer=_passthrough,
                response_deserializer=_passthrough,
            )
            # Temporal's server requires long-poll calls (e.g.
            # PollActivityTaskQueue/PollWorkflowTaskQueue) to carry a
            # deadline ("Context timeout is not set." otherwise), so forward
            # the incoming call's remaining deadline onto the backend call.
            return backend_call(
                request_bytes, metadata=metadata, timeout=context.time_remaining()
            )

        return grpc.unary_unary_rpc_method_handler(
            _unary_unary,
            request_deserializer=_passthrough,
            response_serializer=_passthrough,
        )


class AuthEnforcingProxy:
    """A local gRPC proxy that transparently forwards every call to a real
    backend Temporal server, except it rejects calls carrying a configured
    ``authorization`` header value with a genuine ``PERMISSION_DENIED`` --
    letting tests exercise the real fatal-error path (sdk-core's poller
    treats any unhandled gRPC status as fatal, see
    ``core/src/worker/mod.rs::activity_poll``) without needing real auth
    infrastructure (Temporal Cloud, an authorizer plugin, etc.).
    """

    def __init__(self, backend_target: str, max_workers: int = 16):
        self.backend_channel = grpc.insecure_channel(backend_target)
        self.deny_authorization: Optional[str] = None
        self._server = grpc.server(futures.ThreadPoolExecutor(max_workers=max_workers))
        self._server.add_generic_rpc_handlers((_PassthroughHandler(self),))
        self._port = self._server.add_insecure_port("127.0.0.1:0")

    @property
    def target(self) -> str:
        """The host:port that clients should connect to instead of the real
        server."""
        return f"127.0.0.1:{self._port}"

    def start(self) -> None:
        self._server.start()

    def deny(self, authorization_value: str) -> None:
        """Start rejecting any call whose ``authorization`` metadata equals
        ``authorization_value`` with ``PERMISSION_DENIED``."""
        self.deny_authorization = authorization_value

    def allow_all(self) -> None:
        """Stop rejecting calls; forward everything again."""
        self.deny_authorization = None

    def stop(self, grace: Optional[float] = 0) -> None:
        self._server.stop(grace)
        self.backend_channel.close()
