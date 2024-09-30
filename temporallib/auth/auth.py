from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Mapping

import requests
from macaroonbakery import bakery, httpbakery
from macaroonbakery.bakery import Macaroon, b64decode, macaroon_to_dict
from macaroonbakery.httpbakery.agent import Agent, AgentInteractor, AuthInfo

from google.oauth2 import service_account
import google.auth.transport.requests
from typing import Union
from dataclasses import asdict
import os


class MacaroonAuthOptions:
    """
    Defines the parameters for authenticating with Candid.
    """

    macaroon_url: str = None
    username: str = None
    keys: KeyPair = None

    def __init__(self, macaroon_url: str = None, username: str = None, keys: KeyPair = None):
        self.macaroon_url = macaroon_url or os.getenv("TEMPORAL_CANDID_URL")
        self.username = username or os.getenv("TEMPORAL_CANDID_USERNAME")
        self.keys = keys or KeyPair()



@dataclass
class GoogleAuthOptions:
    """
    Defines the parameters for authenticating with Google IAM.
    """
    type: str = None
    project_id: str = None
    private_key_id: str = None
    private_key: str = None
    client_email: str = None
    client_id: str = None
    auth_uri: str = None
    token_uri: str = None
    auth_provider_x509_cert_url: str = None
    client_x509_cert_url: str = None

    def __post_init__(self):
        self.type = self.type or os.getenv("TEMPORAL_OIDC_AUTH_TYPE")
        self.project_id = self.project_id or os.getenv("TEMPORAL_OIDC_PROJECT_ID")
        self.private_key_id = self.private_key_id or os.getenv("TEMPORAL_OIDC_PRIVATE_KEY_ID")
        self.private_key = self.private_key or os.getenv("TEMPORAL_OIDC_PRIVATE_KEY")
        self.client_email = self.client_email or os.getenv("TEMPORAL_OIDC_CLIENT_EMAIL")
        self.client_id = self.client_id or os.getenv("TEMPORAL_OIDC_CLIENT_ID")
        self.auth_uri = self.auth_uri or os.getenv("TEMPORAL_OIDC_AUTH_URI")
        self.token_uri = self.token_uri or os.getenv("TEMPORAL_OIDC_TOKEN_URI")
        self.auth_provider_x509_cert_url = self.auth_provider_x509_cert_url or os.getenv("TEMPORAL_OIDC_AUTH_PROVIDER_CERT_URL")
        self.client_x509_cert_url = self.client_x509_cert_url or os.getenv("TEMPORAL_OIDC_CLIENT_CERT_URL")



@dataclass
class KeyPair:
    """
    A structure for storing agent key pair.
    """
    private: str = None
    public: str = None

    def __post_init__(self):
        self.private = self.private or os.getenv("TEMPORAL_CANDID_PRIVATE_KEY")
        self.public = self.public or os.getenv("TEMPORAL_CANDID_PUBLIC_KEY")



@dataclass
class AuthOptions:
    config: Union[MacaroonAuthOptions, GoogleAuthOptions]
    provider: str = None

    def __post_init__(self):
        self.provider = self.provider or os.getenv("TEMPORAL_AUTH_PROVIDER")


class AuthHeaderProvider:
    """
    A class to provide the authorization headers to the Temporal client.
    """

    def __init__(self, auth: AuthOptions):
        self.auth = auth

    def get_headers(self) -> Mapping[str, str]:
        if not self.auth.provider:
            raise TemporalError("auth provider must be specified")

        if self.auth.provider == "candid":
            return self.get_macaroon_headers()
        if self.auth.provider == "google":
            return self.get_google_iam_headers()
        raise TemporalError(
            "auth provider not supported. please specify candid or google."
        )

    def get_google_iam_headers(self) -> Mapping[str, str]:
        try:
            auth_dict = asdict(self.auth.config)
            credentials = service_account.Credentials.from_service_account_info(
                auth_dict,
                scopes=[
                    "email",
                    "profile",
                    "openid",
                ],
            )

            auth_req = google.auth.transport.requests.Request()

            if not credentials.valid:
                credentials.refresh(auth_req)

            return {"authorization": f"Bearer {credentials.token}"}
        except Exception as err:
            raise TemporalError(f"error creating oauth token: {err}")

    def get_macaroon_headers(self) -> Mapping[str, str]:
        """
        Retrieves the macaroon from Temporal server, discharges it and returns the according header.
        :return: A header entry for the authorization field
        """
        # get the macaroon from temporal server
        resp = requests.get(self.auth.config.macaroon_url)
        if resp.status_code != 200:
            raise TemporalError(
                f"error reaching the macaroon server ({self.auth.config.macaroon_url})"
                f" response code - {resp.status_code}"
            )

        # decode and extract candid url
        mc_serialized = b64decode(resp.text)
        macaroon = Macaroon.deserialize_json(mc_serialized)
        if len(macaroon.macaroon.caveats) == 0:
            raise TemporalError(f"retrieved macaroon is missing caveats")
        auth_url = macaroon.macaroon.caveats[0].location

        # set up bakery agent and connection
        auth_info = AuthInfo(
            key=bakery.PrivateKey.deserialize(self.auth.config.keys.private),
            agents=[Agent(url=auth_url, username=self.auth.config.username)],
        )
        client = httpbakery.Client(interaction_methods=[AgentInteractor(auth_info)])

        # discharge macaroon
        ms = bakery.discharge_all(macaroon, client.acquire_discharge, client.key)

        # convert it to byte and encode
        ms_dicts = [macaroon_to_dict(m) for m in ms]
        ms_bytes = json.dumps(ms_dicts).encode()
        ms_b64_str = base64.b64encode(ms_bytes).decode()

        # add it to header
        return {"authorization": f"Macaroon {ms_b64_str}"}


class TemporalError(Exception):
    """Exception raised when temporal gives an unexpected response."""
