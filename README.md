# temporal-lib-py

This library provides a partial wrapper for the _Client.connect_ method from
[temporalio/sdk-python](https://github.com/temporalio/sdk-python/tree/main/temporalio)
by adding candid-based authentication, Google IAM-based authentication and
encryption. It also provides a partial wrapper for the Temporal Worker by adding
a Sentry interceptor which can be enabled through config.

## Building

This library uses [poetry](https://github.com/python-poetry/poetry) for
packaging and managing dependencies. To build the wheel file simply run:

```bash
poetry build -f wheel
```

## Usage

### Client

The following code shows how a client connection is created by using the
original (vanilla) temporalio sdk:

```python
from temporalio.client import Client
async def main():
    client = await Client.connect("localhost:7233")
    ...
```

In order to add authorization and encryption capabilities to this client we
replace the connect call as follows:

#### Candid-based authorization

```python
from temporallib.client import Client, Options
from temporallib.auth import AuthOptions, MacaroonAuthOptions, KeyPair
from temporallib.encryption import EncryptionOptions
async def main():
    # alternatively options could be loaded from a yaml file as the one showed below
    cfg = Options(
        host="localhost:7233",
        auth=AuthOptions(provider="candid", config=MacaroonAuthOptions(keys=KeyPair(...))),
        encryption=EncryptionOptions(key="key")
        ...
    )
    client = await Client.connect(cfg)
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
  config:
    macaroon_url: "http://localhost:7888/macaroon"
    username: "test"
    keys:
      private: "MTIzNDU2NzgxMjM0NTY3ODEyMzQ1Njc4MTIzNDU2Nzg="
      public: "ODc2NTQzMjE4NzY1NDMyMTg3NjU0MzIxODc2NTQzMjE="
tls_root_cas: |
  'base64 certificate'
```

#### Google IAM-based authorization

```python
from temporallib.client import Client, Options
from temporallib.auth import AuthOptions, GoogleAuthOptions
from temporallib.encryption import EncryptionOptions
async def main():
    # alternatively options could be loaded from a yaml file as the one showed below
    cfg = Options(
        host="localhost:7233",
        auth=AuthOptions(provider="google", config=GoogleAuthOptions(private_key=...)),
        encryption=EncryptionOptions(key="key")
        ...
    )
    client = await Client.connect(cfg)
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
  config:
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

### Worker

The following code shows how a Worker is created by using the original (vanilla)
temporalio sdk:

```python
from temporalio.worker import Worker
from temporalio.client import Client
async def main():
    client = await Client.connect("localhost:7233")
    worker = Worker(
        client,
        task_queue=task_queue,
        workflows=workflows,
        activities=activities,
    )
    await worker.run()
    ...
```

In order to add Sentry logging capabilities to this worker we replace the worker
initialization as follows:

```python
from temporallib.worker import Worker, WorkerOptions, SentryOptions
from temporallib.client import Client

client = await Client.connect(cfg)
worker = Worker(
    client,
    task_queue=task_queue,
    workflows=workflows,
    activities=activities,
    worker_opt=WorkerOptions(sentry=SentryOptions(dsn="dsn", release="release", environment="environment", redact_params=True)),
)
await worker.run()

```

Note that you can optionally enable parameter redaction to hide event parameters
that are sent to Sentry.

## Samples

More examples of workflows using this library can be found here:

- [temporal-lib-samples](https://github.com/canonical/temporal-lib-samples)
