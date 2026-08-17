"""core/crypto.py — AES-256-GCM with Argon2id key derivation (PBKDF2
fallback if argon2 isn't installed). Trimmed port of JARVIS_V5's
core/crypto.py: just derive_key/encrypt/decrypt, since that's all
core/scatter.py needs — no file-streaming, signing, or benchmark helpers
that would just be unused surface area here.
"""
from __future__ import annotations
import secrets
import time
import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend

try:
    from argon2.low_level import hash_secret_raw, Type
    _ARGON2_OK = True
except ImportError:
    _ARGON2_OK = False


@dataclass
class DerivedKey:
    key: bytes
    salt: bytes
    algorithm: str
    time_ms: float


def derive_key(passphrase: str | bytes, salt: bytes | None = None, length: int = 32) -> DerivedKey:
    """argon2id if available (memory-hard, GPU-resistant); PBKDF2-SHA256
    at 600k iterations otherwise."""
    salt = salt or secrets.token_bytes(32)
    pw = passphrase.encode() if isinstance(passphrase, str) else passphrase
    t0 = time.perf_counter()

    if _ARGON2_OK:
        key = hash_secret_raw(
            secret=pw, salt=salt,
            time_cost=3, memory_cost=65536, parallelism=4,
            hash_len=length, type=Type.ID,
        )
        method = "argon2id"
    else:
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=length, salt=salt,
                          iterations=600_000, backend=default_backend())
        key = kdf.derive(pw)
        method = "pbkdf2"

    elapsed = (time.perf_counter() - t0) * 1000
    log.debug("Key derived via %s in %.1f ms", method, elapsed)
    return DerivedKey(key=key, salt=salt, algorithm=method, time_ms=elapsed)


def encrypt(plaintext: bytes, key: bytes, aad: bytes | None = None) -> bytes:
    """Returns: nonce(12) + ciphertext+tag."""
    nonce = secrets.token_bytes(12)
    return nonce + AESGCM(key).encrypt(nonce, plaintext, aad)


def decrypt(blob: bytes, key: bytes, aad: bytes | None = None) -> bytes:
    nonce, ct = blob[:12], blob[12:]
    return AESGCM(key).decrypt(nonce, ct, aad)
