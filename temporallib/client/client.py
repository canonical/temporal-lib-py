from __future__ import annotations

import asyncio
import dataclasses
import logging
import os
import time
from typing import Callable, Iterable, Mapping, Optional, Union

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from temporalio.client import Client as TemporalClient
from temporalio.client import Interceptor, OutboundInterceptor
from temporalio.common import QueryRejectCondition
from temporalio.converter import DataConverter, default
from temporalio.runtime import PrometheusConfig, Runtime, TelemetryConfig
from temporalio.service import (
    HttpConnectProxyConfig,
    KeepAliveConfig,
    RetryConfig,
    TLSConfig,
)

from temporallib.auth import AuthHeaderProvider, AuthOptions
from temporallib.auth.auth import token_fingerprint
from temporallib.encryption import EncryptionOptions, EncryptionPayloadCodec

logging.basicConfig(level=logging.INFO)


class ProxyOptions(BaseSettings):
    host: Optional[str] = None
    username: Optional[str] = None
    password: Optional[SecretStr] = None

    model_config = SettingsConfigDict(env_prefix="TEMPORAL_PROXY_")

    @model_validator(mode="after")
    def _validate_credentials(self) -> "ProxyOptions":
        if self.password and not self.username:
            raise ValueError("proxy username is required when a proxy password is set")
        if (self.username or self.password) and not self.host:
            raise ValueError("proxy host is required when proxy credentials are set")
        return self


class Options(BaseSettings):
    host: Optional[str] = None
    queue: Optional[str] = None
    namespace: Optional[str] = None
    encryption: Optional[EncryptionOptions] = None
    tls_root_cas: Optional[str] = None
    auth: Optional[AuthOptions] = None
    prometheus_port: Optional[str] = None
    proxy: ProxyOptions = Field(default_factory=ProxyOptions)
    # Default 30m, min 15m, max 60m
    token_refresh_interval: int = Field(default=1800, ge=900, le=3600)

    model_config = SettingsConfigDict(env_prefix="TEMPORAL_")


Options.model_rebuild()


def _init_runtime_with_prometheus(port: int) -> Runtime:
    """Create runtime for use with Prometheus metrics.

    Args:
        port: Port of prometheus.

    Returns:
        Runtime for temporalio with prometheus.
    """
    return Runtime(
        telemetry=TelemetryConfig(
            metrics=PrometheusConfig(bind_address=f"0.0.0.0:{port}")
        )
    )


class Client:
    """
    A class which wraps the :class:`temporalio.client.Client` class with reconnect logic.
    """

    _client: TemporalClient = None
    _is_stop_token_refresh = False
    _initial_backoff = 60
    _max_backoff = 600
    _token_refresh_interval: Optional[int] = None
    _last_token_fingerprint: Optional[str] = None
    _last_token_fetched_at: Optional[float] = None
    _reconnect_task: asyncio.Task | None = None

    @classmethod
    async def stop_reconnect(cls) -> None:
        """Stop and await the reconnect loop.

        This method sets the stop flag and cancels the background reconnect task
        (if any), awaiting its completion. Safe to call multiple times and during/after
        shutdown. Suitable for use in on_fatal_error callbacks.
        """
        logging.info("Stopping Client reconnect loop before worker shutdown...")
        await cls._cancel_reconnect_task()
        logging.info("Reconnect loop successfully stopped.")

    @classmethod
    def disconnect(cls) -> None:
        """Deprecated: Stops the reconnect loop and closes the client.

        This method is synchronous for backward compatibility. For cleaner shutdown,
        prefer the async stop_reconnect() method or call it via asyncio.run_coroutine_threadsafe().
        This method signals the reconnect loop to stop and attempts to cancel any
        background task, but does not await its completion. To guarantee the task
        is stopped, use stop_reconnect() instead.

        This method clears references to the underlying client and runtime.
        """
        # Signal reconnect loop to stop
        cls._is_stop_token_refresh = True

        # Cancel the background reconnect task if it exists (but don't await)
        if cls._reconnect_task:
            cls._reconnect_task.cancel()
            cls._reconnect_task = None

        if hasattr(cls, "_client"):
            del cls._client
        if hasattr(cls, "_runtime"):
            del cls._runtime

    @classmethod
    def instance(self) -> Optional[TemporalClient]:
        """Returns the underlying TemporalClient instance, if it exists."""
        return self._client

    @classmethod
    async def _get_auth_headers(self, auth: AuthOptions) -> Mapping[str, str]:
        auth_header_provider = AuthHeaderProvider(auth)
        loop = asyncio.get_running_loop()
        headers = await loop.run_in_executor(None, auth_header_provider.get_headers)
        self._record_token(headers)
        return headers

    @classmethod
    def _record_token(self, headers: Mapping[str, str]) -> None:
        value = headers.get("authorization")
        if not value:
            return
        self._last_token_fingerprint = token_fingerprint(value)
        self._last_token_fetched_at = time.time()
        logging.info(
            "Auth token refreshed: fingerprint=%s next_refresh_in=%ss",
            self._last_token_fingerprint,
            self._token_refresh_interval,
        )

    @classmethod
    def log_token_state_on_fatal_error(self, exc: BaseException) -> None:
        """Log which token the worker was last given and how old it is, to tell
        a stale token from one rejected while still fresh."""
        if self._last_token_fetched_at is None:
            logging.error("Fatal error with no auth token on record: %r", exc)
            return
        logging.error(
            "Fatal error; last auth token fingerprint=%s age=%.0fs refresh_interval=%ss "
            "reconnect_loop_active=%s error=%r",
            self._last_token_fingerprint,
            time.time() - self._last_token_fetched_at,
            self._token_refresh_interval,
            self._reconnect_task is not None and not self._reconnect_task.done(),
            exc,
        )

    @classmethod
    def _build_proxy_config(
        self, proxy: ProxyOptions
    ) -> Optional[HttpConnectProxyConfig]:
        if not proxy or not proxy.host:
            return None
        basic_auth = None
        if proxy.username:
            password = proxy.password.get_secret_value() if proxy.password else ""
            basic_auth = (proxy.username, password)
        return HttpConnectProxyConfig(target_host=proxy.host, basic_auth=basic_auth)

    @classmethod
    async def _cancel_reconnect_task(self) -> None:
        task = self._reconnect_task
        self._reconnect_task = None
        self._is_stop_token_refresh = True
        if not task or task.done():
            return

        try:
            current_loop = asyncio.get_running_loop()
            task_loop = task.get_loop()
        except RuntimeError:
            return

        if task_loop is current_loop and not task_loop.is_closed():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    @classmethod
    async def reconnect_loop(self):
        """
        Reconnects to the Temporal server periodically when the token expires.
        """
        if self._token_refresh_interval is None:
            raise RuntimeError(
                "Client.reconnect_loop() started without Client.connect() having "
                "run; _token_refresh_interval is unset."
            )

        backoff = self._initial_backoff
        while not self._is_stop_token_refresh:
            try:
                await self._reconnect()
                backoff = self._initial_backoff
                # Refresh tokens according to the configured interval
                # OAuth tokens last 60 minutes
                await asyncio.sleep(self._token_refresh_interval)
                logging.info("Refreshing token and reconnecting to Temporal server...")
            except Exception as e:
                logging.error(f"Failed to reconnect to Temporal server: {e}")
                logging.info(
                    f"Retrying connection to Temporal server in {backoff} seconds..."
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self._max_backoff)

    @classmethod
    async def connect(
        self,
        client_opt: Options,
        *,
        data_converter: DataConverter = default(),
        interceptors: Iterable[
            Union[Interceptor, Callable[[OutboundInterceptor], OutboundInterceptor]]
        ] = None,
        default_workflow_query_reject_condition: Optional[QueryRejectCondition] = None,
        tls: Union[bool, TLSConfig] = False,
        retry_config: Optional[RetryConfig] = None,
        rpc_metadata: Mapping[str, str] = None,
        identity: Optional[str] = None,
        lazy: bool = False,
        runtime: Optional[Runtime] = None,
        keep_alive_config: Optional[KeepAliveConfig] = None,
    ) -> TemporalClient:
        """
        A method which wraps the temporal :func:`temporalio.client.Client.connect` method by adding
        authorization headers and encrypting payloads.
        :param client_opt: the additional options for authorization and encryption
        :param data_converter: pass through to `Client.connect` if encryption not enabled in client_opt
        :param interceptors: pass through parameter to `Client.connect()`
        :param default_workflow_query_reject_condition: pass through parameter to `Client.connect()`
        :param tls: pass through parameter to `Client.connect()` if tls certificate not specified in client_opt
        :param retry_config: pass through parameter to `Client.connect()`
        :param rpc_metadata: pass through parameter to `Client.connect()` if authentication not enabled in client_opt
        :param identity: pass through parameter to `Client.connect()`
        :param lazy: pass through parameter to `Client.connect()`
        :param runtime: pass through parameter to `Client.connect()`
        :return: temporal client used to send or retrieve tasks
        """
        await self._cancel_reconnect_task()
        self._is_stop_token_refresh = False

        # Store the passed connection parameters for reconnection purposes
        self._client_opts = client_opt
        self._data_converter = data_converter
        self._interceptors = interceptors or []
        self._default_workflow_query_reject_condition = (
            default_workflow_query_reject_condition
        )
        self._tls = tls
        self._retry_config = retry_config
        self._rpc_metadata = rpc_metadata or {}
        self._identity = identity
        self._lazy = lazy
        self._runtime = runtime
        self._keep_alive_config = keep_alive_config
        self._http_connect_proxy_config = self._build_proxy_config(client_opt.proxy)
        self._token_refresh_interval = client_opt.token_refresh_interval

        if client_opt.auth:
            self._rpc_metadata.update(await self._get_auth_headers(client_opt.auth))

        if client_opt.encryption and client_opt.encryption.key:
            encryption_codec = EncryptionPayloadCodec(client_opt.encryption.key)
            self._data_converter = dataclasses.replace(
                self._data_converter, payload_codec=encryption_codec
            )

        if client_opt.tls_root_cas:
            enc_tls_root_cas = client_opt.tls_root_cas.encode()
            host = client_opt.host.split(":")[0]
            self._tls = TLSConfig(server_root_ca_cert=enc_tls_root_cas, domain=host)

        if self._runtime is None and client_opt.prometheus_port:
            self._runtime = _init_runtime_with_prometheus(
                int(client_opt.prometheus_port)
            )

        self._client = await TemporalClient.connect(
            self._client_opts.host,
            namespace=self._client_opts.namespace
            or os.getenv("TEMPORAL_NAMESPACE")
            or "default",
            data_converter=self._data_converter,
            interceptors=self._interceptors,
            default_workflow_query_reject_condition=self._default_workflow_query_reject_condition,
            tls=self._tls,
            retry_config=self._retry_config,
            rpc_metadata=self._rpc_metadata,
            identity=self._identity,
            lazy=self._lazy,
            runtime=self._runtime,
            keep_alive_config=self._keep_alive_config,
            http_connect_proxy_config=self._http_connect_proxy_config,
        )

        # Start reconnect loop in background and keep a reference
        self._reconnect_task = asyncio.create_task(self.reconnect_loop())

        return self._client

    @classmethod
    async def _reconnect(self):
        # Refresh the auth headers before reconnecting
        if self._client_opts.auth:
            self._client.rpc_metadata = {
                **self._client.rpc_metadata,
                **await self._get_auth_headers(self._client_opts.auth),
            }

        logging.debug("Testing Temporal server connection")
        await self._client.count_workflows()
