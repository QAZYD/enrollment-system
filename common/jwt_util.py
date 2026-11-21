"""Shared JWT helpers. Every node uses the SAME secret, so any service can
verify a token locally without calling the auth node (stateless sessions)."""
import os
import time

import jwt

SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me")
ALGO = "HS256"
TTL_SECONDS = 60 * 60  # 1 hour


def make(username: str, role: str) -> str:
    """Create a signed token. Used by the auth service (and by test scripts)."""
    now = int(time.time())
    payload = {"sub": username, "role": role, "iat": now, "exp": now + TTL_SECONDS}
    return jwt.encode(payload, SECRET, algorithm=ALGO)


def verify(token: str) -> dict:
    """Return the claims {sub, role, iat, exp}. Raises jwt.InvalidTokenError if bad/expired."""
    return jwt.decode(token, SECRET, algorithms=[ALGO], leeway=30)


def claims_or_none(token: str):
    """Like verify(), but returns None instead of raising. Handy inside RPC handlers."""
    try:
        return verify(token)
    except jwt.InvalidTokenError:
        return None
