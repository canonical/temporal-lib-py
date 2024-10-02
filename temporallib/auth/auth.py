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
from pydantic_settings import BaseSettings
from pydantic import Field, BaseModel


class MacaroonAuthOptions(BaseSettings):
    macaroon_url: str = Field(None, alias="TEMPORAL_CANDID_URL")
    username: str
    keys: Optional[KeyPair]

    class Config:
        env_prefix = 'TEMPORAL_CANDID_'
        populate_by_name = True

class GoogleAuthOptions(BaseSettings):
    type: str = "service_account"
    project_id: str
    private_key_id: str
    private_key: str
    client_email: str
    client_id: str
    auth_uri: str = "https://accounts.google.com/o/oauth2/auth"
    token_uri: str = "https://oauth2.googleapis.com/token"
    auth_provider_x509_cert_url: str = "https://www.googleapis.com/oauth2/v1/certs"
    client_x509_cert_url: Optional[str] = Field(None, alias="TEMPORAL_OIDC_CLIENT_CERT_URL")

    class Config:
        env_prefix = 'TEMPORAL_OIDC_'
        populate_by_name = True

class KeyPair(BaseSettings):
    private: str = Field(None, alias="TEMPORAL_CANDID_PRIVATE_KEY")
    public: str = Field(None, alias="TEMPORAL_CANDID_PUBLIC_KEY")

    class Config:
        populate_by_name = True



class AuthOptions(BaseSettings):
    config: Optional[Union[MacaroonAuthOptions, GoogleAuthOptions]] = None
    provider: str

    class Config:
        env_prefix = 'TEMPORAL_AUTH_'


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
            auth_dict = self.auth.config.model_dump()
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
