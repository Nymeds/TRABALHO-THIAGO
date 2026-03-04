import base64
import hashlib
import hmac
import secrets
from typing import Dict


def _derive_key(shared_secret: str) -> bytes:
    if not shared_secret:
        raise ValueError("shared_secret cannot be empty")
    return hashlib.sha256(shared_secret.encode("utf-8")).digest()


def _keystream(key: bytes, nonce: bytes, size: int) -> bytes:
    stream = bytearray()
    counter = 0
    while len(stream) < size:
        counter_bytes = counter.to_bytes(8, "big")
        stream.extend(hashlib.sha256(key + nonce + counter_bytes).digest())
        counter += 1
    return bytes(stream[:size])


def _b64encode(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _b64decode(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))


def encrypt_text(plaintext: str, shared_secret: str) -> Dict[str, str]:
    key = _derive_key(shared_secret)
    nonce = secrets.token_bytes(16)
    data = plaintext.encode("utf-8")
    stream = _keystream(key, nonce, len(data))
    ciphertext = bytes(a ^ b for a, b in zip(data, stream))
    tag = hmac.new(key, nonce + ciphertext, hashlib.sha256).digest()
    return {
        "nonce": _b64encode(nonce),
        "ciphertext": _b64encode(ciphertext),
        "tag": _b64encode(tag),
    }


def decrypt_text(payload: Dict[str, str], shared_secret: str) -> str:
    key = _derive_key(shared_secret)
    try:
        nonce = _b64decode(payload["nonce"])
        ciphertext = _b64decode(payload["ciphertext"])
        received_tag = _b64decode(payload["tag"])
    except Exception as exc:
        raise ValueError("invalid encrypted payload") from exc

    expected_tag = hmac.new(key, nonce + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(received_tag, expected_tag):
        raise ValueError("message authentication failed")

    stream = _keystream(key, nonce, len(ciphertext))
    plaintext = bytes(a ^ b for a, b in zip(ciphertext, stream))
    return plaintext.decode("utf-8")
