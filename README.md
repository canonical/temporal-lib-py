# temporal-lib-py

This library provides a partial wrapper for the _Client.connect_ method from
[temporalio/sdk-python](https://github.com/temporalio/sdk-python/tree/main/temporalio)
by adding candid-based authentication, Google IAM-based authentication and
encryption.

## Building

This library uses [poetry](https://github.com/python-poetry/poetry) for
packaging and managing dependencies. To build the wheel file simply run:

```bash
poetry build -f wheel
```

## Usage

The following code shows how a client connection is created using by using the
original (vanilla) temporalio sdk:

```python
from temporalio.client import Client
async def main():
    client = await Client.connect("localhost:7233")
    ...
```

In order to add authorization and encryption capabilities to this client we
replace the connect call as follows:

### Candid-based authorization

```python
from temporallib.connection import Connection, Options
from temporallib.auth import MacaroonAuthOptions, KeyPair
from temporallib.encryption import EncryptionOptions
async def main():
    # alternatively options could be loaded from a yaml file as the one showed below
    cfg = Options(
        host="localhost:7233",
        auth=MacaroonAuthOptions(provider="candid", keys=KeyPair(...))
        encryption=EncryptionOptions(key="key")
        ...
    )
    client = await Connection.connect(cfg)
	...
```

The structure of the YAML file which can be used to construct the Options is as
follows:

```yaml
host: "localhost:7233"
queue: "test-queue"
namespace: "test"
encryption:
  key: "HLCeMJLLiyLrUOukdThNgRfyraIXZk918rtp5VX/uwI="
auth:
  provider: "candid"
  macaroon_url: "http://localhost:7888/macaroon"
  username: "test"
  keys:
    private: "MTIzNDU2NzgxMjM0NTY3ODEyMzQ1Njc4MTIzNDU2Nzg="
    public: "ODc2NTQzMjE4NzY1NDMyMTg3NjU0MzIxODc2NTQzMjE="
tls_root_cas: |
  'base64 certificate'
```

### Google IAM-based authorization

```python
from temporallib.connection import Connection, Options
from temporallib.auth import GoogleAuthOptions
from temporallib.encryption import EncryptionOptions
async def main():
    # alternatively options could be loaded from a yaml file as the one showed below
    cfg = Options(
        host="localhost:7233",
        auth=GoogleAuthOptions(provider="google", private_key=...)
        encryption=EncryptionOptions(key="key")
        ...
    )
    client = await Connection.connect(cfg)
	...
```

The structure of the YAML file which can be used to construct the Options is as
follows:

```yaml
host: "localhost:7233"
queue: "test-queue"
namespace: "test"
encryption:
  key: "HLCeMJLLiyLrUOukdThNgRfyraIXZk918rtp5VX/uwI="
auth:
  provider: "google"
  type: "service_account"
  project_id: "REPLACE_WITH_PROJECT_ID"
  private_key_id: "REPLACE_WITH_PRIVATE_KEY_ID"
  private_key: "REPLACE_WITH_PRIVATE_KEY"
  client_email: "REPLACE_WITH_CLIENT_EMAIL"
  client_id: "REPLACE_WITH_CLIENT_ID"
  auth_uri: "https://accounts.google.com/o/oauth2/auth"
  token_uri: "https://oauth2.googleapis.com/token"
  auth_provider_x509_cert_url: "https://www.googleapis.com/oauth2/v1/certs"
  client_x509_cert_url: "REPLACE_WITH_CLIENT_CERT_URL"
tls_root_cas: |
  'base64 certificate'
```

## Samples

More examples of workflows using this library can be found here:

- [temporal-lib-samples](https://github.com/canonical/temporal-lib-samples)
