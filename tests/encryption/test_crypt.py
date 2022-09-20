from temporallib.encryption import decrypt, encrypt


def test_encode_decode():
    key = b"[ 16 bytes key ]"
    secret_msg = b"this is top secret"
    enc_msg = encrypt(secret_msg, key)
    dec_msg = decrypt(enc_msg, key)
    assert secret_msg == dec_msg
