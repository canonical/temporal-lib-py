from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Mapping

import requests
from macaroonbakery import bakery, httpbakery
from macaroonbakery.bakery import Macaroon, b64decode, macaroon_to_dict
from macaroonbakery.httpbakery.agent import Agent, AgentInteractor, AuthInfo


@dataclass
class AuthOptions:
    """
    Defines the parameters for authenticating with Candid.
    """

    macaroon_url: str
    username: str
    keys: KeyPair


@dataclass
class KeyPair:
    """
    A structure for storing agent the key pair.
    """

    private: str
    public: str = None


class AuthHeaderProvider:
    """
    A class to provide the authorization headers to the Temporal client.
    """

    def __init__(self, cfg: AuthOptions):
        self.cfg = cfg

    def get_headers(self) -> Mapping[str, str]:
        """
        Retrieves the macaroon from Temporal server, discharges it and returns the according header.
        :return: A header entry for the authorization field
        """
        # get the macaroon from temporal server
        resp = requests.get(self.cfg.macaroon_url)
        if resp.status_code != 200:
            raise TemporalError(
                f"error reaching the macaroon server ({self.cfg.macaroon_url})"
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
            key=bakery.PrivateKey.deserialize(self.cfg.keys.private),
            agents=[Agent(url=auth_url, username=self.cfg.username)],
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
