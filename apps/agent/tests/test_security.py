"""Unit tests for cryptographic security utilities (covers: AC-5)."""

import base64

import pytest

from app.core.security import (
    _decode_key,
    decrypt_secret,
    encrypt_secret,
    generate_encryption_key,
)
from app.domain.exceptions import DecryptionError


def test_generate_and_decode_key():
    """Verify generated key is 32 bytes valid base64."""
    key_b64 = generate_encryption_key()
    assert isinstance(key_b64, str)
    raw_key = _decode_key(key_b64)
    assert len(raw_key) == 32


def test_invalid_key_length():
    """Verify error when key is not 32 bytes."""
    short_key = base64.b64encode(b"too_short").decode("utf-8")
    with pytest.raises(DecryptionError, match="must be exactly 32 bytes"):
        _decode_key(short_key)


def test_encrypt_and_decrypt_happy_path():
    """Verify encryption and decryption round-trip."""
    key = generate_encryption_key()
    secret = "ghp_1234567890abcdefghijklmnopqrstuvwxyz"

    encrypted_data, nonce = encrypt_secret(secret, key)
    assert encrypted_data != secret
    assert isinstance(encrypted_data, str)
    assert isinstance(nonce, str)

    decrypted = decrypt_secret(encrypted_data, nonce, key)
    assert decrypted == secret


def test_decrypt_tampered_ciphertext_fails():
    """Verify authentication tag verification catches tampered ciphertext."""
    key = generate_encryption_key()
    secret = "super_secret_api_key_123"

    encrypted_data, nonce = encrypt_secret(secret, key)

    raw_data = bytearray(base64.b64decode(encrypted_data))
    raw_data[0] ^= 0xFF
    tampered_data = base64.b64encode(raw_data).decode("utf-8")

    with pytest.raises(DecryptionError, match="tag mismatch or corrupted data"):
        decrypt_secret(tampered_data, nonce, key)


def test_decrypt_tampered_nonce_fails():
    """Verify tampering with nonce causes decryption failure."""
    key = generate_encryption_key()
    secret = "another_secret"

    encrypted_data, nonce = encrypt_secret(secret, key)

    raw_nonce = bytearray(base64.b64decode(nonce))
    raw_nonce[0] ^= 0xFF
    tampered_nonce = base64.b64encode(raw_nonce).decode("utf-8")

    with pytest.raises(DecryptionError, match="tag mismatch or corrupted data"):
        decrypt_secret(encrypted_data, tampered_nonce, key)


def test_decrypt_with_wrong_key_fails():
    """Verify decrypting with a different 32-byte key fails."""
    key1 = generate_encryption_key()
    key2 = generate_encryption_key()
    secret = "secret_token"

    encrypted_data, nonce = encrypt_secret(secret, key1)

    with pytest.raises(DecryptionError, match="tag mismatch or corrupted data"):
        decrypt_secret(encrypted_data, nonce, key2)
