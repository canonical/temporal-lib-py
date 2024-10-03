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
    A class which wraps the :class:`temporalio.client.Client` class
    """
    
    _is_stop_token_refresh = False

    @classmethod
    def __del__(self):
        self._is_stop_token_refresh = True

    @classmethod
    async def update_rpc_metadata_loop(self, client_opt, rpc_metadata):
        """
        Periodically update the rpc_metadata headers
        """
        while not self._is_stop_token_refresh:
            # By default, refresh every 55 minutes. This is because Google OAuth
            # tokens expire after 60 minutes.
            await asyncio.sleep(3300)
            auth_header_provider = AuthHeaderProvider(client_opt.auth)
            rpc_metadata.update(auth_header_provider.get_headers())

    @staticmethod
    async def connect(
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
        if interceptors is None:
            interceptors = []

        if rpc_metadata is None:
            rpc_metadata = {}

        namespace = client_opt.namespace or os.getenv("TEMPORAL_NAMESPACE") or "default"

        if client_opt.auth:
            auth_header_provider = AuthHeaderProvider(client_opt.auth)
            rpc_metadata = dict(rpc_metadata)
            rpc_metadata.update(auth_header_provider.get_headers())
            
            # Start a task to periodically update rpc_metadata
            asyncio.create_task(Client.update_rpc_metadata_loop(client_opt, rpc_metadata))

        if client_opt.encryption and client_opt.encryption.key:
            encryption_codec = EncryptionPayloadCodec(client_opt.encryption.key)
            data_converter = dataclasses.replace(
                data_converter, payload_codec=encryption_codec
            )

        if client_opt.tls_root_cas:
            enc_tls_root_cas = client_opt.tls_root_cas.encode()
            host = client_opt.host.split(":")[0]
            tls = TLSConfig(server_root_ca_cert=enc_tls_root_cas, domain=host)

        if runtime is None and client_opt.prometheus_port:
            runtime = _init_runtime_with_prometheus(int(client_opt.prometheus_port))

        return await TemporalClient.connect(
            client_opt.host,
            namespace=namespace,
            data_converter=data_converter,
            interceptors=interceptors,
            default_workflow_query_reject_condition=default_workflow_query_reject_condition,
            tls=tls,
            retry_config=retry_config,
            rpc_metadata=rpc_metadata,
            identity=identity,
            lazy=lazy,
            runtime=runtime,
            keep_alive_config=keep_alive_config,
        )
