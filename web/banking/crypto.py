import base64
import hashlib
from django.conf import settings
from cryptography.fernet import Fernet


def get_fernet_key() -> bytes:
    """
    Derives a deterministic 32-byte URL-safe base64 key from Django SECRET_KEY.
    """
    secret = settings.SECRET_KEY.encode('utf-8')
    key_32bytes = hashlib.sha256(secret).digest()
    return base64.urlsafe_b64encode(key_32bytes)


def encrypt_secret(plaintext: str) -> str:
    """
    Encrypts a secret string using Fernet symmetric encryption.
    """
    if not plaintext:
        return ""
    f = Fernet(get_fernet_key())
    encrypted_bytes = f.encrypt(plaintext.encode('utf-8'))
    return encrypted_bytes.decode('utf-8')


def decrypt_secret(ciphertext: str) -> str:
    """
    Decrypts a Fernet encrypted string.
    """
    if not ciphertext:
        return ""
    f = Fernet(get_fernet_key())
    decrypted_bytes = f.decrypt(ciphertext.encode('utf-8'))
    return decrypted_bytes.decode('utf-8')
