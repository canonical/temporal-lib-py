from dataclasses import dataclass
from typing import Iterable, List

from temporalio.api.common.v1 import Payload
from temporalio.converter import PayloadCodec

from temporallib.encryption.crypt import decrypt, encrypt


@dataclass
class EncryptionOptions:
    """
    Defines the parameters for encrypting workflow arguments
    """

    key: str
    compress: bool = False


class EncryptionPayloadCodec(PayloadCodec):
    """
    The codec class used by the DataConverter to encode and decode workflow arguments.
    """

    ENCODING = b"binary/encrypted"

    def __init__(self, key: bytes):
        self.key = key

    async def encode(self, payloads: Iterable[Payload]) -> List[Payload]:
        enc_payloads = []
        for p in payloads:
            enc_p = Payload()
            enc_p.metadata["encoding"] = EncryptionPayloadCodec.ENCODING
            enc_p.data = encrypt(p.SerializeToString(), self.key)
            enc_payloads.append(enc_p)
        return enc_payloads

    async def decode(self, payloads: Iterable[Payload]) -> List[Payload]:
        dec_payloads = []
        for p in payloads:
            if p.metadata["encoding"] != EncryptionPayloadCodec.ENCODING:
                continue
            dec_data = decrypt(p.data, self.key)
            dec_p = Payload()
            dec_p.ParseFromString(dec_data)
            dec_payloads.append(dec_p)
        return dec_payloads
