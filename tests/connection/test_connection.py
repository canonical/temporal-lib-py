from unittest.mock import MagicMock

import pytest
import requests
from macaroonbakery import bakery
from temporalio.workflow_service import WorkflowService

from temporallib.auth import AuthOptions, KeyPair
from temporallib.connection import Connection, Options
from temporallib.encryption import EncryptionOptions, EncryptionPayloadCodec
from tests.auth.test_auth import mock_discharge_all, mock_get


async def mock_connect(_):
    return MagicMock()


@pytest.mark.asyncio
async def test_connect(monkeypatch):
    monkeypatch.setattr(requests, "get", mock_get)
    monkeypatch.setattr(bakery, "discharge_all", mock_discharge_all)
    monkeypatch.setattr(WorkflowService, "connect", mock_connect)
    opts = Options(
        host="test",
        queue="test queue",
        namespace="test namespace",
        auth=AuthOptions(
            macaroon_url="macaroon url",
            username="test user",
            keys=KeyPair(
                private="MTIzNDU2NzgxMjM0NTY3ODEyMzQ1Njc4MTIzNDU2Nzg=",
                public="public key",
            ),
        ),
        encryption=EncryptionOptions(key="encryption key"),
        tls_root_cas="certificate",
    )

    client = await Connection.connect(opts)
    assert client.namespace == opts.namespace
    assert isinstance(client.data_converter.payload_codec, EncryptionPayloadCodec)
