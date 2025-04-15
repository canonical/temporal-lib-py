from unittest.mock import MagicMock

import pytest
import requests
from google.oauth2 import service_account
from macaroonbakery import bakery
from temporalio.service import ServiceClient

from temporallib.auth import (
    AuthOptions,
    GoogleAuthOptions,
    KeyPair,
    MacaroonAuthOptions,
)
from temporallib.client import Client, Options
from temporallib.encryption import EncryptionOptions, EncryptionPayloadCodec
from tests.auth.test_auth import mock_discharge_all, mock_get_macaroon, mock_get_token


async def mock_connect(_):
    return MagicMock()


@pytest.mark.asyncio
async def test_connect_candid(monkeypatch):
    monkeypatch.setattr(requests, "get", mock_get_macaroon)
    monkeypatch.setattr(bakery, "discharge_all", mock_discharge_all)
    monkeypatch.setattr(ServiceClient, "connect", mock_connect)
    opts = Options(
        host="test",
        queue="test queue",
        namespace="test namespace",
        auth=AuthOptions(
            provider="candid",
            config=MacaroonAuthOptions(
                macaroon_url="test",
                username="test",
                keys=KeyPair(
                    private="MTIzNDU2NzgxMjM0NTY3ODEyMzQ1Njc4MTIzNDU2Nzg=",
                    public="public",
                ),
            ),
        ),
        encryption=EncryptionOptions(
            key="MTIzNDU2NzgxMjM0NTY3ODEyMzQ1Njc4MTIzNDU2Nzg="
        ),
        tls_root_cas="certificate",
    )

    client = await Client.connect(opts)
    assert client.namespace == opts.namespace
    assert isinstance(client.data_converter.payload_codec, EncryptionPayloadCodec)


@pytest.mark.asyncio
async def test_connect_candid_env_variables(monkeypatch):
    monkeypatch.setenv("TEMPORAL_HOST", "test")
    monkeypatch.setenv("TEMPORAL_QUEUE", "test queue")
    monkeypatch.setenv("TEMPORAL_NAMESPACE", "test namespace")

    monkeypatch.setenv("TEMPORAL_AUTH_PROVIDER", "candid")
    monkeypatch.setenv("TEMPORAL_CANDID_URL", "test_url")
    monkeypatch.setenv("TEMPORAL_CANDID_USERNAME", "test")
    monkeypatch.setenv(
        "TEMPORAL_CANDID_PRIVATE_KEY", "MTIzNDU2NzgxMjM0NTY3ODEyMzQ1Njc4MTIzNDU2Nzg="
    )
    monkeypatch.setenv("TEMPORAL_CANDID_PUBLIC_KEY", "public")

    monkeypatch.setenv(
        "TEMPORAL_ENCRYPTION_KEY", "MTIzNDU2NzgxMjM0NTY3ODEyMzQ1Njc4MTIzNDU2Nzg="
    )
    monkeypatch.setenv("TEMPORAL_TLS_ROOT_CAS", "certificate")

    monkeypatch.setattr(requests, "get", mock_get_macaroon)
    monkeypatch.setattr(bakery, "discharge_all", mock_discharge_all)
    monkeypatch.setattr(ServiceClient, "connect", mock_connect)

    opts = Options(
        auth=AuthOptions(config=MacaroonAuthOptions(keys=KeyPair())),
        encryption=EncryptionOptions(),
    )

    client = await Client.connect(opts)
    assert client.namespace == opts.namespace
    assert isinstance(opts.auth, AuthOptions)
    assert isinstance(opts.auth.config, MacaroonAuthOptions)
    assert isinstance(client.data_converter.payload_codec, EncryptionPayloadCodec)


@pytest.mark.asyncio
async def test_connect_google(monkeypatch):
    monkeypatch.setattr(
        service_account.Credentials, "from_service_account_info", mock_get_token
    )
    monkeypatch.setattr(ServiceClient, "connect", mock_connect)
    opts = Options(
        host="test",
        queue="test queue",
        namespace="test namespace",
        auth=AuthOptions(
            provider="google",
            config=GoogleAuthOptions(
                type="service_account",
                project_id="test",
                private_key_id="test",
                private_key="test",
                client_email="test",
                client_id="test",
                auth_uri="https://accounts.google.com/o/oauth2/auth",
                token_uri="https://oauth2.googleapis.com/token",
                auth_provider_x509_cert_url="https://www.googleapis.com/oauth2/v1/certs",
                client_x509_cert_url="test",
            ),
        ),
        encryption=EncryptionOptions(
            key="MTIzNDU2NzgxMjM0NTY3ODEyMzQ1Njc4MTIzNDU2Nzg="
        ),
        tls_root_cas="certificate",
    )

    client = await Client.connect(opts)
    assert client.namespace == opts.namespace
    assert isinstance(client.data_converter.payload_codec, EncryptionPayloadCodec)


@pytest.mark.asyncio
async def test_connect_google_env_variables(monkeypatch):
    monkeypatch.setenv("TEMPORAL_HOST", "test")
    monkeypatch.setenv("TEMPORAL_QUEUE", "test queue")
    monkeypatch.setenv("TEMPORAL_NAMESPACE", "test namespace")

    monkeypatch.setenv("TEMPORAL_AUTH_PROVIDER", "google")
    monkeypatch.setenv("TEMPORAL_OIDC_AUTH_TYPE", "service_account")
    monkeypatch.setenv("TEMPORAL_OIDC_PROJECT_ID", "test")
    monkeypatch.setenv("TEMPORAL_OIDC_PRIVATE_KEY_ID", "test")
    monkeypatch.setenv("TEMPORAL_OIDC_PRIVATE_KEY", "test")
    monkeypatch.setenv("TEMPORAL_OIDC_CLIENT_EMAIL", "test")
    monkeypatch.setenv("TEMPORAL_OIDC_CLIENT_ID", "test")
    monkeypatch.setenv(
        "TEMPORAL_OIDC_AUTH_URI", "https://accounts.google.com/o/oauth2/auth"
    )
    monkeypatch.setenv("TEMPORAL_OIDC_TOKEN_URI", "https://oauth2.googleapis.com/token")
    monkeypatch.setenv(
        "TEMPORAL_OIDC_AUTH_PROVIDER_CERT_URL",
        "https://www.googleapis.com/oauth2/v1/certs",
    )
    monkeypatch.setenv("TEMPORAL_OIDC_CLIENT_CERT_URL", "test")

    monkeypatch.setenv(
        "TEMPORAL_ENCRYPTION_KEY", "MTIzNDU2NzgxMjM0NTY3ODEyMzQ1Njc4MTIzNDU2Nzg="
    )
    monkeypatch.setenv("TEMPORAL_TLS_ROOT_CAS", "certificate")

    monkeypatch.setattr(
        service_account.Credentials, "from_service_account_info", mock_get_token
    )
    monkeypatch.setattr(ServiceClient, "connect", mock_connect)

    opts = Options(
        auth=AuthOptions(config=GoogleAuthOptions()), encryption=EncryptionOptions()
    )

    client = await Client.connect(opts)
    assert client.namespace == opts.namespace
    assert isinstance(opts.auth, AuthOptions)
    assert isinstance(opts.auth.config, GoogleAuthOptions)
    assert isinstance(client.data_converter.payload_codec, EncryptionPayloadCodec)
