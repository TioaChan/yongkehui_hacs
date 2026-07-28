"""Password encoding helpers for the YongKeHui login API."""

from __future__ import annotations

import base64
import binascii
import re

from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from cryptography.hazmat.primitives.serialization import load_der_public_key

from .exceptions import InvalidAuth

_DEFAULT_PASSWORD_PUBLIC_KEY = (
    "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC03KMpYBkJ51nCrWUsMr1E3T5/"
    "q8ETu/UbeJnbyjYD4u3F/4iEECLbUxe9k49gQcb4rR2zciI0Oy8R3x1Irndjc81f"
    "9w9g2fTqNnsM00siVsqh6VGEV9XBkWOUoyg601WNbR3HiIa3GyLvo79oND0mdFBP"
    "0QqQc2h7IMqaR71hEwIDAQAB"
)
_RSA_PADDING_OVERHEAD = 11
_PUBLIC_KEY_CANDIDATE = re.compile(r"""["']([A-Za-z0-9+/]{150,}={0,2})["']""")


def encode_password(password: str, public_key: str | None = None) -> str:
    """Return the login password field expected by YongKeHui.

    The app does Base64.encode(form.password), then RSA encryptLong with
    randomized PKCS#1 v1.5 padding. Keep encrypted-value passthrough for
    existing configs created from packet captures.
    """

    if _looks_like_encrypted_password(password):
        return password.strip()

    encoded_password = base64.b64encode(password.encode("utf-8"))
    return _rsa_encrypt_long(encoded_password, public_key or _DEFAULT_PASSWORD_PUBLIC_KEY)


def parse_public_key(script: str) -> str | None:
    """Extract the first valid DER RSA public key embedded in JavaScript."""

    for candidate in _PUBLIC_KEY_CANDIDATE.findall(script):
        if _load_public_key(candidate) is not None:
            return candidate
    return None


def _looks_like_encrypted_password(value: str) -> bool:
    text = value.strip()
    if len(text) != 172:
        return False
    try:
        return len(base64.b64decode(text, validate=True)) == 128
    except ValueError:
        return False


def _rsa_encrypt_long(plaintext: bytes, public_key_text: str) -> str:
    public_key = _load_public_key(public_key_text)
    if public_key is None:
        raise InvalidAuth("永客会 RSA 公钥无效")

    max_chunk_size = public_key.key_size // 8 - _RSA_PADDING_OVERHEAD
    # JSEncrypt encryptLong joins hex blocks and then converts hex to Base64;
    # joining encrypted bytes and Base64-encoding the result is equivalent.
    encrypted_chunks = [
        public_key.encrypt(
            plaintext[index : index + max_chunk_size],
            padding.PKCS1v15(),
        )
        for index in range(0, len(plaintext), max_chunk_size)
    ]
    return base64.b64encode(b"".join(encrypted_chunks)).decode("ascii")


def _load_public_key(public_key_text: str) -> RSAPublicKey | None:
    try:
        key = load_der_public_key(base64.b64decode(public_key_text, validate=True))
    except (binascii.Error, ValueError):
        return None
    return key if isinstance(key, RSAPublicKey) else None
