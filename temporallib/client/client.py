from __future__ import annotations

import asyncio
import dataclasses
import logging
import os
from typing import Callable, Iterable, Mapping, Optional, Union

from pydantic_settings import BaseSettings
from temporalio.client import Client as TemporalClient
from temporalio.client import Interceptor, OutboundInterceptor
from temporalio.common import QueryRejectCondition
from temporalio.converter import DataConverter, default
from temporalio.runtime import PrometheusConfig, Runtime, TelemetryConfig
from temporalio.service import KeepAliveConfig, RetryConfig, TLSConfig

from temporallib.auth import AuthHeaderProvider, AuthOptions
from temporallib.encryption import EncryptionOptions, EncryptionPayloadCodec

logging.basicConfig(level=logging.INFO)


class Options(BaseSettings):
    host: Optional[str] = None
    queue: Optional[str] = None
    namespace: Optional[str] = None
    encryption: Optional[EncryptionOptions] = None
    tls_root_cas: Optional[str] = None
    auth: Optional[AuthOptions] = None
    prometheus_port: Optional[str] = None

    class Config:
        env_prefix = "TEMPORAL_"


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

    _is_stop_token_refresh = False
    _initial_backoff = 60
    _max_backoff = 600
    _token_refresh_interval = 3300

    @classmethod
    def __del__(self):
        self._is_stop_token_refresh = True

    @classmethod
    async def reconnect_loop(self):
        """
        Reconnects to the Temporal server periodically when the token expires.
        """
        backoff = self._initial_backoff
        while not self._is_stop_token_refresh:
            try:
                await self._reconnect()
                backoff = self._initial_backoff
                await asyncio.sleep(
                    self._token_refresh_interval
                )  # Refresh tokens every ~55 minutes (OAuth tokens last 60 minutes)
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

        if client_opt.auth:
            auth_header_provider = AuthHeaderProvider(client_opt.auth)
            self._rpc_metadata.update(auth_header_provider.get_headers())

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
            namespace=self._client_opts.namespace or os.getenv("TEMPORAL_NAMESPACE") or "default",
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
        )

        asyncio.create_task(self.reconnect_loop())
        
        return self._client

    @classmethod
    async def _reconnect(self):
        # Refresh the auth headers before reconnecting
        if self._client_opts.auth:
            auth_header_provider = AuthHeaderProvider(self._client_opts.auth)
            self._client.rpc_metadata = {**self._client.rpc_metadata, **auth_header_provider.get_headers()}

        logging.debug("Testing Temporal server connection")
        await self._client.count_workflows()
