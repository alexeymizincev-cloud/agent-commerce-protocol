"""
Cryptographic primitives for ACP atomic delivery.

Key innovation: preimage = decryption key.
- Provider generates random preimage K (32 bytes)
- hash H = SHA256(K) — embedded in Lightning hold invoice
- Result encrypted with AES-256-CBC, key derived from K
- Consumer pays hold invoice → provider settles → K revealed
- Consumer decrypts result with K
"""

import os
import hashlib
import base64
from typing import Optional

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad


def generate_preimage() -> bytes:
    """Generate a random 256-bit preimage (32 bytes).

    This IS the decryption key AND the Lightning preimage.
    """
    return os.urandom(32)


def hash_preimage(preimage: bytes) -> bytes:
    """SHA256 hash of preimage (32 bytes).

    This goes into the Lightning hold invoice: H = SHA256(K).
    """
    return hashlib.sha256(preimage).digest()


def encrypt_result(result: bytes, preimage: bytes) -> bytes:
    """Encrypt result with AES-256-CBC using preimage as key.

    Key = first 32 bytes of preimage (already 32 bytes = 256 bits).
    IV = deterministic from preimage hash (not secret, just needs to be unique).

    Returns: IV (16 bytes) + ciphertext (variable), packed as raw bytes.
    For Nostr event: base64-encode the result.
    """
    key = preimage  # 32 bytes = AES-256
    iv = hashlib.sha256(preimage + b"iv").digest()[:16]  # deterministic, non-secret

    cipher = AES.new(key, AES.MODE_CBC, iv)
    ct = cipher.encrypt(pad(result, AES.block_size))

    return iv + ct


def decrypt_result(encrypted: bytes, preimage: bytes) -> bytes:
    """Decrypt result with AES-256-CBC using preimage as key.

    Reverses encrypt_result: split IV (first 16 bytes) + ciphertext.
    """
    key = preimage
    iv = encrypted[:16]
    ct = encrypted[16:]

    cipher = AES.new(key, AES.MODE_CBC, iv)
    pt = unpad(cipher.decrypt(ct), AES.block_size)

    return pt


def encrypt_result_b64(result: bytes, preimage: bytes) -> str:
    """Encrypt and return as base64 string (for Nostr event tag)."""
    return base64.b64encode(encrypt_result(result, preimage)).decode('ascii')


def decrypt_result_b64(encrypted_b64: str, preimage: bytes) -> bytes:
    """Decrypt base64-encoded encrypted result."""
    return decrypt_result(base64.b64decode(encrypted_b64), preimage)


def verify_preimage(preimage: bytes, expected_hash: bytes) -> bool:
    """Verify that SHA256(preimage) == expected_hash."""
    return hash_preimage(preimage) == expected_hash


def verify_receipt(offer_preimage_hash: bytes, receipt_preimage: bytes) -> bool:
    """Verify that receipt preimage matches offer's preimage_hash.

    This proves:
    1. Payment settled (Lightning requires correct preimage to settle)
    2. Result can be decrypted (preimage IS the decryption key)
    """
    return hash_preimage(receipt_preimage) == offer_preimage_hash