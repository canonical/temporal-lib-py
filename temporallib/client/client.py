from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping, Optional, Union

from temporalio.client import Client as TemporalClient
from temporalio.client import Interceptor, OutboundInterceptor
from temporalio.common import QueryRejectCondition
from temporalio.converter import DataConverter, default
from temporalio.service import TLSConfig, RetryConfig, KeepAliveConfig
from temporalio.runtime import (
    PrometheusConfig,
    Runtime,
    TelemetryConfig,
)

from temporallib.auth import AuthHeaderProvider, AuthOptions, MacaroonAuthOptions, GoogleAuthOptions, KeyPair
from temporallib.encryption import EncryptionOptions, EncryptionPayloadCodec
from typing import Union
import asyncio
from pydantic_settings import BaseSettings
import os
import logging


class Options(BaseSettings):
    host: Optional[str] = None
    queue: Optional[str] = None
    namespace: Optional[str] = None
    encryption: Optional[EncryptionOptions] = None
    tls_root_cas: Optional[str] = None
    auth: Optional[AuthOptions] = None
    prometheus_port: Optional[str] = None

    class Config:
        env_prefix = 'TEMPORAL_'

Options.model_rebuild()

def _init_runtime_with_prometheus(port: int) -> Runtime:
    """Create runtime for use with Prometheus metrics.

    Args:
        port: Port of prometheus.

    Returns:
        Runtime for temporalio with prometheus.
    """
    return Runtime(telemetry=TelemetryConfig(metrics=PrometheusConfig(bind_address=f"0.0.0.0:{port}")))

class Client:
    """
    A class which wraps the :class:`temporalio.client.Client` class with reconnect logic.
    """

    _is_stop_token_refresh = False

    @classmethod
    def __del__(cls):
        cls._is_stop_token_refresh = True

    @classmethod
    async def reconnect_loop(cls):
        """
        Reconnects to the Temporal server periodically when the token expires.
        """
        while not cls._is_stop_token_refresh:
            try:
                await asyncio.sleep(3300)  # Refresh tokens every ~55 minutes (OAuth tokens last 60 min)
                logging.info("Refreshing token and reconnecting to Temporal server...")
                await cls._reconnect()
            except Exception as e:
                logging.error(f"Failed to reconnect to Temporal server: {e}")
                await asyncio.sleep(60)  # Backoff before retrying

    @classmethod
    async def connect(
        cls,
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
        Connects to the Temporal server and automatically reconnects upon token expiry.
        """
        # Store the passed connection parameters for reconnection purposes
        cls._client_opts = client_opt
        cls._data_converter = data_converter
        cls._interceptors = interceptors or []
        cls._default_workflow_query_reject_condition = default_workflow_query_reject_condition
        cls._tls = tls
        cls._retry_config = retry_config
        cls._rpc_metadata = rpc_metadata or {}
        cls._identity = identity
        cls._lazy = lazy
        cls._runtime = runtime
        cls._keep_alive_config = keep_alive_config

        if client_opt.auth:
            auth_header_provider = AuthHeaderProvider(client_opt.auth)
            cls._rpc_metadata.update(auth_header_provider.get_headers())

        if client_opt.encryption and client_opt.encryption.key:
            encryption_codec = EncryptionPayloadCodec(client_opt.encryption.key)
            cls._data_converter = dataclasses.replace(
                cls._data_converter, payload_codec=encryption_codec
            )

        if client_opt.tls_root_cas:
            enc_tls_root_cas = client_opt.tls_root_cas.encode()
            host = client_opt.host.split(":")[0]
            cls._tls = TLSConfig(server_root_ca_cert=enc_tls_root_cas, domain=host)

        if cls._runtime is None and client_opt.prometheus_port:
            cls._runtime = _init_runtime_with_prometheus(int(client_opt.prometheus_port))

        asyncio.create_task(cls.reconnect_loop())

        return await TemporalClient.connect(
            client_opt.host,
            namespace=client_opt.namespace or os.getenv("TEMPORAL_NAMESPACE") or "default",
            data_converter=cls._data_converter,
            interceptors=cls._interceptors,
            default_workflow_query_reject_condition=cls._default_workflow_query_reject_condition,
            tls=cls._tls,
            retry_config=cls._retry_config,
            rpc_metadata=cls._rpc_metadata,
            identity=cls._identity,
            lazy=cls._lazy,
            runtime=cls._runtime,
            keep_alive_config=cls._keep_alive_config,
        )

    @classmethod
    async def _reconnect(cls):
        """
        Internal method to reconnect using the saved parameters.
        """
        if cls._client_opts:
            # Refresh the auth headers before reconnecting
            if cls._client_opts.auth:
                auth_header_provider = AuthHeaderProvider(cls._client_opts.auth)
                cls._rpc_metadata.update(auth_header_provider.get_headers())
            
            await TemporalClient.connect(
                cls._client_opts.host,
                namespace=cls._client_opts.namespace or os.getenv("TEMPORAL_NAMESPACE") or "default",
                data_converter=cls._data_converter,
                interceptors=cls._interceptors,
                default_workflow_query_reject_condition=cls._default_workflow_query_reject_condition,
                tls=cls._tls,
                retry_config=cls._retry_config,
                rpc_metadata=cls._rpc_metadata,
                identity=cls._identity,
                lazy=cls._lazy,
                runtime=cls._runtime,
                keep_alive_config=cls._keep_alive_config,
            )
