"""Password hashing, signed session cookies, login rate limiting, CSRF."""

from __future__ import annotations

import secrets
import time

import bcrypt
from fastapi import HTTPException, Request
from itsdangerous import BadSignature, URLSafeTimedSerializer

from . import config

COOKIE = "session"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def generate_password(words: int = 4) -> str:
    """Readable, easy to type: 'casa-verde-1234'-style."""
    return secrets.token_urlsafe(9)


class Sessions:
    def __init__(self, secret: str):
        self._s = URLSafeTimedSerializer(secret, salt="session")

    def issue(self, username: str) -> str:
        return self._s.dumps({"u": username, "csrf": secrets.token_urlsafe(16)})

    def read(self, token: str | None) -> dict | None:
        if not token:
            return None
        try:
            return self._s.loads(token, max_age=config.SESSION_DAYS * 86400)
        except BadSignature:
            return None


class LoginLimiter:
    """5 failures per (username, ip) -> 15 minute lockout. In-memory; single web process."""

    def __init__(self):
        self._fails: dict[tuple[str, str], list[float]] = {}

    def locked(self, key: tuple[str, str]) -> bool:
        recent = [t for t in self._fails.get(key, []) if time.time() - t < config.LOGIN_LOCKOUT_S]
        self._fails[key] = recent
        return len(recent) >= config.LOGIN_MAX_FAILURES

    def fail(self, key: tuple[str, str]) -> None:
        self._fails.setdefault(key, []).append(time.time())

    def reset(self, key: tuple[str, str]) -> None:
        self._fails.pop(key, None)


def require_csrf(request: Request, session: dict, token: str | None) -> None:
    if not token or not secrets.compare_digest(token, session.get("csrf", "")):
        raise HTTPException(status_code=403, detail="CSRF")
