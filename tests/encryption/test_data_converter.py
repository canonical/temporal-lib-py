import base64

from temporallib.encryption import EncryptionKeyException, EncryptionPayloadCodec


def test_decode_key():
    # wrong b64 encoding
    b64_key = "HLCeMJLLiyLrUOukdThNgRfyraIXZk918rtp5VX"
    try:
        EncryptionPayloadCodec.decode_key(b64_key)
        assert False
    except EncryptionKeyException as eke:
        print(eke)
        assert True

    # wrong length
    b64_key = "MTIzNDU="
    try:
        EncryptionPayloadCodec.decode_key(b64_key)
        assert False
    except EncryptionKeyException as eke:
        print(eke)
        assert True

    # fine
    b64_key = "HLCeMJLLiyLrUOukdThNgRfyraIXZk918rtp5VX/uwI="
    try:
        EncryptionPayloadCodec.decode_key(b64_key)
        assert True
    except EncryptionKeyException:
        assert False
