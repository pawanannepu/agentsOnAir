"""Cryptographic security utilities for credential encryption and decryption.

Uses AES 256 GCM authenticated encryption with 96-bit initialization vectors (nonces)
and 128-bit authentication tags to protect sensitive credentials at rest.
"""

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.domain.exceptions import DecryptionError


def generate_encryption_key() -> str:
    """Generate a random 32-byte key suitable for AES-256-GCM, returned as base64."""
    key = AESGCM.generate_key(bit_length=256)
    return base64.b64encode(key).decode("utf-8")


def _decode_key(key_base64: str) -> bytes:
    """Validate and decode a base64 encryption key into 32 raw bytes."""
    try:
        raw_key = base64.b64decode(key_base64)
    except Exception as exc:
        raise DecryptionError(f"Invalid base64 encryption key: {exc}") from exc

    if len(raw_key) != 32:
        raise DecryptionError(
            f"Encryption key must be exactly 32 bytes (256 bits), got {len(raw_key)}"
        )
    return raw_key


def encrypt_secret(plaintext: str, key_base64: str) -> tuple[str, str]:
    """Encrypt plaintext using AES-256-GCM.

    Returns:
        tuple[str, str]: (encrypted_data_base64, nonce_base64)
        The encrypted_data contains ciphertext with the 16-byte authentication tag.
    """
    key = _decode_key(key_base64)
    aesgcm = AESGCM(key)

    # 96-bit nonce (12 bytes) recommended for AES-GCM
    nonce = os.urandom(12)
    plaintext_bytes = plaintext.encode("utf-8")

    # AESGCM.encrypt appends 16-byte authentication tag to the ciphertext
    ciphertext_with_tag = aesgcm.encrypt(nonce, plaintext_bytes, None)

    encrypted_data_b64 = base64.b64encode(ciphertext_with_tag).decode("utf-8")
    nonce_b64 = base64.b64encode(nonce).decode("utf-8")

    return encrypted_data_b64, nonce_b64


def decrypt_secret(
    encrypted_data_base64: str,
    nonce_base64: str,
    key_base64: str,
) -> str:
    """Decrypt ciphertext with authentication tag verification using AES-256-GCM.

    Raises:
        DecryptionError: if tag verification fails or data is corrupted/tampered.
    """
    key = _decode_key(key_base64)
    aesgcm = AESGCM(key)

    try:
        ciphertext_with_tag = base64.b64decode(encrypted_data_base64)
        nonce = base64.b64decode(nonce_base64)
    except Exception as exc:
        raise DecryptionError(f"Invalid base64 payload: {exc}") from exc

    if len(nonce) != 12:
        raise DecryptionError(
            f"Invalid nonce length: expected 12 bytes, got {len(nonce)}"
        )

    try:
        decrypted_bytes = aesgcm.decrypt(nonce, ciphertext_with_tag, None)
        return decrypted_bytes.decode("utf-8")
    except Exception as exc:
        raise DecryptionError(
            f"Failed to decrypt secret: tag mismatch or corrupted data ({exc})"
        ) from exc
