"""Security primitives: Fernet encryption, bcrypt hashing, session cookies."""

from __future__ import annotations

import time
from dataclasses import dataclass

import bcrypt
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Response
from itsdangerous import URLSafeTimedSerializer

from app.core.config import settings

# ── Fernet singleton ──────────────────────────────────────────────────────────

_fernet: Fernet | None = None


class TokenEncryptionNotConfigured(RuntimeError):
    """Raised when Fernet encryption is invoked without a configured key.

    Distinct from a generic `RuntimeError` so the FastAPI exception
    handler can convert it into a structured 503 with a useful
    `detail.code` (instead of the opaque 500 the user was seeing
    before: `Internal Server Error`, 21 bytes, no info).
    """


def get_fernet() -> Fernet:
    """Return a cached Fernet instance initialised with token_encryption_key.

    Raises:
        TokenEncryptionNotConfigured: when token_encryption_key is missing.
    """
    global _fernet
    if _fernet is not None:
        return _fernet
    if not settings.token_encryption_key:
        raise TokenEncryptionNotConfigured(
            "token_encryption_key is not configured. "
            "Set FERNET_KEY in .env (run Settings.generate_fernet_key() to create one)."
        )
    _fernet = Fernet(settings.token_encryption_key.encode("utf-8"))
    return _fernet


def encrypt_token(plain: str) -> str:
    """Fernet-encrypt a plaintext token. Returns a base64 string."""
    return get_fernet().encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt_token(cipher: str) -> str:
    """Decrypt a Fernet-encrypted token.

    Raises:
        InvalidToken: when the cipher text is malformed or the key is wrong.
    """
    return get_fernet().decrypt(cipher.encode("utf-8")).decode("utf-8")


# ── Password hashing ───────────────────────────────────────────────────────────

COOKIE_NAME = "pulseorder_session"


def hash_password(pw: str) -> str:
    """Hash a plaintext password with bcrypt (cost factor 12)."""
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(pw.encode("utf-8"), salt).decode("utf-8")


def verify_password(pw: str, hash_str: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    return bcrypt.checkpw(pw.encode("utf-8"), hash_str.encode("utf-8"))


# ── Session token ──────────────────────────────────────────────────────────────

_SERIALIZER_SALT = "pulseorder-session"


@dataclass
class SessionToken:
    """A signed, time-limited session token payload."""

    user_id: int
    exp: int  # Unix timestamp

    def to_signed(self, secret: str) -> str:
        """Return a signed token string using itsdangerous URLSafeTimedSerializer."""
        serializer = URLSafeTimedSerializer(secret, salt=_SERIALIZER_SALT)
        return serializer.dumps({"user_id": self.user_id, "exp": self.exp})

    @classmethod
    def from_signed(cls, token: str, secret: str, max_age_seconds: int) -> "SessionToken | None":
        """Verify and deserialise a signed token.

        Returns None if the token is absent, tampered, expired per
        ``max_age_seconds`` *or* per the payload's own ``exp`` field.
        """
        serializer = URLSafeTimedSerializer(secret, salt=_SERIALIZER_SALT)
        try:
            data = serializer.loads(token, max_age=max_age_seconds)
        except Exception:  # itsdangerous raises BadSignature / SignatureExpired
            return None
        # Also honour the payload's own exp (defence in depth)
        if data.get("exp") is not None and int(data["exp"]) < int(time.time()):
            return None
        return cls(user_id=data["user_id"], exp=data["exp"])


# ── Cookie helpers ────────────────────────────────────────────────────────────

def _extract_cookie_domain(request: "Request | None") -> str | None:
    """Return the cookie domain matching the request Host header, or None.

    When the browser talks to the Next.js proxy (e.g. localhost:3001) which
    forwards to the API (e.g. 127.0.0.1:8123), the Host header carries the
    proxy's origin so the browser stores the cookie for the right host.
    Without this, the cookie would be scoped to the API's bind address
    (127.0.0.1) and the browser would NOT send it when the proxy is on
    localhost — causing silent 401s on every authenticated request.
    """
    if request is None:
        return None
    host: str = request.headers.get("host", "")
    # Strip port number so we get a clean domain.
    host = host.split(":")[0]
    # Only set domain for non-empty, non-loopback hosts.
    if not host or host in ("localhost", "127.0.0.1", "::1"):
        return None
    return host


# Re-import settings lazily at runtime to avoid circular imports at module scope
def create_session_cookie(
    response: Response,
    user_id: int,
    request: "Request | None" = None,
) -> None:
    """Sign a session for user_id and attach it as an HttpOnly cookie."""
    payload = SessionToken(user_id=user_id, exp=int(time.time()) + 86400 * 7)
    signed = payload.to_signed(settings.session_secret)
    response.set_cookie(
        key=COOKIE_NAME,
        value=signed,
        httponly=True,
        samesite="lax",
        secure=settings.require_https,
        path="/",
        domain=_extract_cookie_domain(request),
    )


def clear_session_cookie(
    response: Response,
    request: "Request | None" = None,
) -> None:
    """Delete the session cookie, matching the domain used when it was set."""
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        domain=_extract_cookie_domain(request),
    )
