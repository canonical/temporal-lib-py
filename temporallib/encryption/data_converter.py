import base64
import binascii
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

    def __init__(self, b64_key: str):
        self.key = EncryptionPayloadCodec.decode_key(b64_key)

    @staticmethod
    def decode_key(b64_key):
        try:
            key = base64.b64decode(b64_key)
        except binascii.Error:
            raise EncryptionKeyException("Incorrect base64 encoding")

        accepted_lengths = (8, 16, 32)
        if len(key) not in accepted_lengths:
            raise EncryptionKeyException(
                f"Wrong key length {len(key)}. Should be one of {accepted_lengths}"
            )
        return key

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


class EncryptionKeyException(Exception):
    """Exception thrown when the encryption key is not valid"""
