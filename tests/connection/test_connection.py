from unittest.mock import MagicMock

import pytest
import requests
from macaroonbakery import bakery
from temporalio.service import ServiceClient

from temporallib.auth import MacaroonAuthOptions, GoogleAuthOptions, KeyPair
from temporallib.connection import Connection, Options
from temporallib.encryption import EncryptionOptions, EncryptionPayloadCodec
from tests.auth.test_auth import mock_discharge_all, mock_get_macaroon, mock_get_token
from google.oauth2 import service_account

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
        auth=MacaroonAuthOptions(
            provider="candid",
            macaroon_url="macaroon url",
            username="test user",
            keys=KeyPair(
                private="MTIzNDU2NzgxMjM0NTY3ODEyMzQ1Njc4MTIzNDU2Nzg=",
                public="public key",
            ),
        ),
        encryption=EncryptionOptions(key="MTIzNDU2NzgxMjM0NTY3ODEyMzQ1Njc4MTIzNDU2Nzg="),
        tls_root_cas="certificate",
    )

    client = await Connection.connect(opts)
    assert client.namespace == opts.namespace
    assert isinstance(client.data_converter.payload_codec, EncryptionPayloadCodec)

@pytest.mark.asyncio
async def test_connect_google(monkeypatch):
    monkeypatch.setattr(service_account.Credentials, "from_service_account_info", mock_get_token)
    monkeypatch.setattr(ServiceClient, "connect", mock_connect)
    opts = Options(
        host="test",
        queue="test queue",
        namespace="test namespace",
        auth=GoogleAuthOptions(
            provider="google",
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
        encryption=EncryptionOptions(key="MTIzNDU2NzgxMjM0NTY3ODEyMzQ1Njc4MTIzNDU2Nzg="),
        tls_root_cas="certificate",
    )

    client = await Connection.connect(opts)
    assert client.namespace == opts.namespace
    assert isinstance(client.data_converter.payload_codec, EncryptionPayloadCodec)
