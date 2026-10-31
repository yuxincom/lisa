from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from .config import JWT_SECRET, JWT_TTL_HOURS

PBKDF2_ITERATIONS = 120_000


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ITERATIONS)
    return f"pbkdf2${PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt, expected = stored.split("$")
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt.encode(), int(iterations)
        )
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError):
        return False


def _sign(message: str) -> str:
    return _b64encode(hmac.new(JWT_SECRET.encode(), message.encode(), hashlib.sha256).digest())


def create_token(user_id: int, username: str, role: str, name: str) -> str:
    header = _b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    now_ts = int(time.time())
    payload = _b64encode(
        json.dumps(
            {
                "sub": username,
                "uid": user_id,
                "role": role,
                "name": name,
                "iat": now_ts,
                "exp": now_ts + JWT_TTL_HOURS * 3600,
            },
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    )
    message = f"{header}.{payload}"
    return f"{message}.{_sign(message)}"


def decode_token(token: str) -> dict[str, Any] | None:
    try:
        header, payload, signature = token.split(".")
        if not hmac.compare_digest(signature, _sign(f"{header}.{payload}")):
            return None
        data = json.loads(_b64decode(payload))
        if int(data.get("exp", 0)) < int(time.time()):
            return None
        return data
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def signature_digest(plan_code: str, username: str, timestamp: str) -> str:
    raw = f"{plan_code}|{username}|{timestamp}|{JWT_SECRET}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32].upper()
