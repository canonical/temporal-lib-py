from unittest.mock import MagicMock

import requests
from macaroonbakery import bakery

from temporallib.auth import AuthHeaderProvider, MacaroonAuthOptions, GoogleAuthOptions, KeyPair
from google.oauth2 import service_account


def mock_discharge_all(macaroon, method, key):
    fake_macaroon = MagicMock()
    fake_macaroon.serialize = lambda a: '{"fake": "macaroon"}'
    return [fake_macaroon, fake_macaroon]

def mock_get_macaroon(url):
    resp = MagicMock()
    resp.status_code = 200
    resp.text = (
        "eyJtIjp7ImMiOlt7Imk2NCI6IkF3QSIsInY2NCI6Ikh5RS04YTdYRE9tSDl4TFpPdExSQktxRjMzcEtVcGJ3NEpJRU9NaGF1"
        "bUd5ZzZ3ZDNnZlZSLWVITGhIeE5vUFhTOG5zYmVXTS1fbUIxN0Y2YnliWWl2QVhiLW55YjZGWCIsImwiOiJodHRwczovL2Fw"
        "aS5zdGFnaW5nLmp1anVjaGFybXMuY29tL2lkZW50aXR5In0seyJpIjoidGltZS1iZWZvcmUgMjAyMi0wOS0zMFQxMTowMDow"
        "OC40ODY2NDU4MzdaIn1dLCJpNjQiOiJBd29RWmwydG5tcWQyVjFMRDAwLVJXR21LeElnWkdWa1lqZzNPRGsyTVdZMFpERXdP"
        "VEpoTUdaaU5ERTJZemRoWXpnMU5tVWFEZ29GWVdkbGJuUVNCV3h2WjJsdSIsInM2NCI6ImllUHd6M0dJNUFwLWxXdDhkd1Rf"
        "cG8zaWFudVBxNHlTQ0tNNHlrZ3NTbjQifSwidiI6MywiY2RhdGEiOnsiQXdBIjoiQS1XT2k2Qi1lMk5IX3JBRS14S3FLUF9J"
        "N0tCZ1lnNkJORmRTbGp6c2U2TWxjVXg2T1dkZHJaNXFuZGxkU3c5TlBrVmhwaXRMOWxQZWJyMEJsR3M0aEFBcWxCalNRR0xaa"
        "1h0UWV5X015V2t2MUt5bVN3WFdtakVXdUZWNW9JNmhJU21sUGpfR3Qzblk2VjIwNk9zVDczd0N1aVJYN1dMYjlrUzhhZHhGY09G"
        "VCJ9LCJucyI6InN0ZDoifQ"
    )
    return resp

def mock_get_token(cfg_dict, scopes):
    resp = MagicMock()
    resp.status_code = 200
    resp.text = (
        "eyJtIjp7ImMiOlt7Imk2NCI6IkF3QSIsInY2NCI6Ikh5RS04YTdYRE9tSDl4TFpPdExSQktxRjMzcEtVcGJ3NEpJRU9NaGF1"
        "bUd5ZzZ3ZDNnZlZSLWVITGhIeE5vUFhTOG5zYmVXTS1fbUIxN0Y2YnliWWl2QVhiLW55YjZGWCIsImwiOiJodHRwczovL2Fw"
        "aS5zdGFnaW5nLmp1anVjaGFybXMuY29tL2lkZW50aXR5In0seyJpIjoidGltZS1iZWZvcmUgMjAyMi0wOS0zMFQxMTowMDow"
        "OC40ODY2NDU4MzdaIn1dLCJpNjQiOiJBd29RWmwydG5tcWQyVjFMRDAwLVJXR21LeElnWkdWa1lqZzNPRGsyTVdZMFpERXdP"
        "VEpoTUdaaU5ERTJZemRoWXpnMU5tVWFEZ29GWVdkbGJuUVNCV3h2WjJsdSIsInM2NCI6ImllUHd6M0dJNUFwLWxXdDhkd1Rf"
        "cG8zaWFudVBxNHlTQ0tNNHlrZ3NTbjQifSwidiI6MywiY2RhdGEiOnsiQXdBIjoiQS1XT2k2Qi1lMk5IX3JBRS14S3FLUF9J"
        "N0tCZ1lnNkJORmRTbGp6c2U2TWxjVXg2T1dkZHJaNXFuZGxkU3c5TlBrVmhwaXRMOWxQZWJyMEJsR3M0aEFBcWxCalNRR0xaa"
        "1h0UWV5X015V2t2MUt5bVN3WFdtakVXdUZWNW9JNmhJU21sUGpfR3Qzblk2VjIwNk9zVDczd0N1aVJYN1dMYjlrUzhhZHhGY09G"
        "VCJ9LCJucyI6InN0ZDoifQ"
    )
    return resp

def test_get_candid_headers(monkeypatch):
    auth_options = MacaroonAuthOptions(
        macaroon_url="test",
        username="test",
        keys=KeyPair(
            private="MTIzNDU2NzgxMjM0NTY3ODEyMzQ1Njc4MTIzNDU2Nzg=", public="public"
        ),
    )
    auth_provider = AuthHeaderProvider(auth_options)
    monkeypatch.setattr(requests, "get", mock_get_macaroon)
    monkeypatch.setattr(bakery, "discharge_all", mock_discharge_all)
    header = auth_provider.get_headers()
    assert len(header["authorization"]) > 0


def test_get_google_headers(monkeypatch):
    auth_options = GoogleAuthOptions(
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
    )
    auth_provider = AuthHeaderProvider(auth_options)
    monkeypatch.setattr(service_account.Credentials, "from_service_account_info", mock_get_token)
    header = auth_provider.get_headers()
    assert len(header["authorization"]) > 0
