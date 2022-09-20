from Crypto.Cipher import AES


def encrypt(plain_data: bytes, key: bytes):
    """AES encryption of data"""
    cipher = AES.new(key, AES.MODE_EAX)
    nonce = cipher.nonce
    encrypted_data, tag = cipher.encrypt_and_digest(plain_data)
    sealed_encrypted_data = nonce + tag + encrypted_data
    return sealed_encrypted_data


def decrypt(sealed_encrypted_data: bytes, key: bytes):
    """AES decryption of data"""
    nonce = sealed_encrypted_data[: AES.block_size]
    tag = sealed_encrypted_data[AES.block_size : 2 * AES.block_size]
    encrypted_data = sealed_encrypted_data[2 * AES.block_size :]
    cipher = AES.new(key, AES.MODE_EAX, nonce=nonce)
    plain_data = cipher.decrypt(encrypted_data)
    try:
        cipher.verify(tag)
        return plain_data
    except ValueError:
        raise ValueError("incorrect key or message corrupted")
