"""Password hashing (Argon2id), JWT access tokens and opaque refresh tokens."""
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import get_settings

_hasher = PasswordHasher()  # Argon2id with library defaults (memory-hard)

# Pre-computed hash used to equalise timing when a user does not exist
_DUMMY_HASH = _hasher.hash("timing-equaliser-not-a-real-password")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def set_user_password(user, password: str) -> None:
    """Store the password readable (password_plain) and hashed (password_hash)."""
    user.password_plain = password
    user.password_hash = hash_password(password)


def check_user_password(user, password: str) -> bool:
    """Plain column wins when present (so it can be edited in the database console).
    Accounts created before the plain column existed are checked against the hash and get
    their plain value filled in on the first successful sign-in."""
    if user is None:
        verify_password(password, None)  # equalise timing
        return False
    if user.password_plain is not None:
        import hmac
        return hmac.compare_digest(password.encode("utf-8"), user.password_plain.encode("utf-8"))
    ok = verify_password(password, user.password_hash)
    if ok:
        user.password_plain = password
    return ok


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def validate_password_strength(password: str) -> list[str]:
    problems = []
    if len(password) < 10:
        problems.append("at least 10 characters")
    if not any(c.isupper() for c in password):
        problems.append("an uppercase letter")
    if not any(c.islower() for c in password):
        problems.append("a lowercase letter")
    if not any(c.isdigit() for c in password):
        problems.append("a digit")
    return problems


def create_access_token(user_id: int, token_version: str | None = None) -> tuple[str, int]:
    s = get_settings()
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=s.access_token_minutes)
    payload = {
        "sub": str(user_id), "iat": int(now.timestamp()), "exp": int(exp.timestamp()),
        "jti": uuid.uuid4().hex, "typ": "access", "iss": "vision-servicedesk",
    }
    return jwt.encode(payload, s.secret_key, algorithm=s.jwt_algorithm), s.access_token_minutes * 60


def decode_access_token(token: str) -> dict:
    s = get_settings()
    payload = jwt.decode(
        token, s.secret_key, algorithms=[s.jwt_algorithm], issuer="vision-servicedesk",
        options={"require": ["exp", "sub", "iat", "typ"]},
    )
    if payload.get("typ") != "access":
        raise jwt.InvalidTokenError("wrong token type")
    return payload


def new_refresh_token() -> tuple[str, str]:
    """Returns (raw_token, sha256_hash). Only the hash is stored."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_token(raw)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
