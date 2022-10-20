# temporal-lib-py
This library provides a partial wrapper for the *Client.connect* method from [temporalio/sdk-python](https://github.com/temporalio/sdk-python/tree/main/temporalio) by adding candid-based authentication and encryption.


## Building

This library uses [poetry](https://github.com/python-poetry/poetry) for packaging and managing dependencies.
To build the wheel file simply run:
```bash
poetry build -f wheel
```


## Usage

The following code shows how a client connection is created using by using the original (vanilla) temporalio sdk:
```python
from temporalio.client import Client
async def main():
    client = await Client.connect("localhost:7233")
    ...
```
In order to add authorization and encryption capabilities to this client we replace the connect call as following:
```python
from temporallib.connection import Connection, Options
from temporallib.auth import AuthOptions, KeyPair
from temporallib.encryption import EncryptionOptions
async def main():
    # alternatively options could be loaded from a yalm file as the one showed below
    client_opt = Options(
        host="localhost:7233",
        auth=AuthOptions(keys=KeyPair(...))
        encryption=EncryptionOptions(key="key")
        ...
    )
	client = await Connection.connect(client_opt)
	...
```
The structure of the YAML file which can be used to construct the Options is as following:
```yaml
host: 'localhost:7233'
queue: 'test-queue'
namespace: 'test'
encryption:
  key: 'HLCeMJLLiyLrUOukdThNgRfyraIXZk918rtp5VX/uwI='
auth:
  macaroon_url: 'http://localhost:7888/macaroon'
  username: 'test'
  keys:
    private: 'MTIzNDU2NzgxMjM0NTY3ODEyMzQ1Njc4MTIzNDU2Nzg='
    public: 'ODc2NTQzMjE4NzY1NDMyMTg3NjU0MzIxODc2NTQzMjE='
tls_root_cas: |
  'base64 certificate'
```

## Samples
More examples of workflows using this library can be found here:
- [temporal-lib-samples]( https://github.com/canonical/temporal-lib-samples)
