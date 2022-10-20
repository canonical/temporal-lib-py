import base64

from temporallib.encryption import decrypt, encrypt


def test_encode_decode():
    b64_key = "HLCeMJLLiyLrUOukdThNgRfyraIXZk918rtp5VX/uwI="
    key = base64.b64decode(b64_key)
    secret_msg = b"this is top secret"
    enc_msg = encrypt(secret_msg, key)
    dec_msg = decrypt(enc_msg, key)
    assert secret_msg == dec_msg
