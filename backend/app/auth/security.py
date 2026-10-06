"""Password hashing and JWT issuing/validation.

Uses the ``bcrypt`` library directly rather than through passlib, whose 1.7.x
backend inspection breaks against bcrypt 4.x.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from ..config import Settings, settings as default_settings

logger = logging.getLogger(__name__)

BCRYPT_MAX_BYTES = 72


def hash_password(password: str) -> str:
    encoded = password.encode("utf-8")
    if len(encoded) > BCRYPT_MAX_BYTES:
        raise ValueError("Password exceeds the 72-byte bcrypt limit")
    return bcrypt.hashpw(encoded, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        # Malformed stored hash: treat as a failed login rather than a 500.
        return False


def create_access_token(
    subject: str, config: Settings = default_settings, extra_claims: dict | None = None
) -> tuple[str, int]:
    """Return the signed token and its lifetime in seconds."""
    expires_in = config.access_token_expire_minutes * 60
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
        **(extra_claims or {}),
    }
    token = jwt.encode(payload, config.jwt_secret, algorithm=config.jwt_algorithm)
    return token, expires_in


def decode_access_token(token: str, config: Settings = default_settings) -> dict | None:
    try:
        return jwt.decode(token, config.jwt_secret, algorithms=[config.jwt_algorithm])
    except JWTError as exc:
        logger.debug("Rejected token: %s", exc)
        return None
