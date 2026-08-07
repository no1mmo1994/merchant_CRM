"""Tests for app.core.security."""

from __future__ import annotations

import time

import pytest
from cryptography.fernet import InvalidToken

from app.core.config import Settings
from app.core.security import (
    SessionToken,
    clear_session_cookie,
    create_session_cookie,
    decrypt_token,
    encrypt_token,
    hash_password,
    verify_password,
)


class TestEncryptDecrypt:
    """Fernet encrypt/decrypt roundtrip and wrong-key handling."""

    def test_roundtrip(self) -> None:
        key = Settings.generate_fernet_key()
        # Patch settings token_encryption_key for the test scope
        import app.core.security as security

        original = security._fernet
        security._fernet = None  # reset cache
        original_key = security.settings.token_encryption_key

        try:
            security.settings.token_encryption_key = key
            # Reset cache after key change
            security._fernet = None

            plain = "hello grab merchant api token"
            cipher = encrypt_token(plain)
            assert cipher != plain
            assert decrypt_token(cipher) == plain
        finally:
            security.settings.token_encryption_key = original_key
            security._fernet = original

    def test_wrong_key_raises_invalid_token(self) -> None:
        import app.core.security as security

        original = security._fernet
        security._fernet = None
        original_key = security.settings.token_encryption_key

        try:
            security.settings.token_encryption_key = Settings.generate_fernet_key()
            security._fernet = None
            cipher = encrypt_token("secret")

            # Swap to a different key
            security.settings.token_encryption_key = Settings.generate_fernet_key()
            security._fernet = None

            with pytest.raises(InvalidToken):
                decrypt_token(cipher)
        finally:
            security.settings.token_encryption_key = original_key
            security._fernet = original


class TestPasswordHash:
    """bcrypt hash and verify."""

    def test_hash_verify_correct(self) -> None:
        pw = "MyS3cr3t!Pass"
        h = hash_password(pw)
        assert h != pw
        assert len(h) > 40
        assert verify_password(pw, h) is True

    def test_verify_wrong_password(self) -> None:
        h = hash_password("correct")
        assert verify_password("wrong", h) is False

    def test_different_hashes_for_same_password(self) -> None:
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2  # bcrypt uses random salt


class TestSessionToken:
    """Signed session token roundtrip and expiry."""

    def test_sign_verify_roundtrip(self) -> None:
        secret = Settings.generate_session_secret()
        token = SessionToken(user_id=42, exp=int(time.time()) + 3600)
        signed = token.to_signed(secret)
        restored = SessionToken.from_signed(signed, secret, max_age_seconds=3600)
        assert restored is not None
        assert restored.user_id == 42

    def test_expired_token_returns_none(self) -> None:
        secret = Settings.generate_session_secret()
        # Create a token that expired 1 second ago
        token = SessionToken(user_id=99, exp=int(time.time()) - 1)
        signed = token.to_signed(secret)
        restored = SessionToken.from_signed(signed, secret, max_age_seconds=2)
        assert restored is None

    def test_tampered_token_returns_none(self) -> None:
        secret = Settings.generate_session_secret()
        token = SessionToken(user_id=7, exp=int(time.time()) + 3600)
        signed = token.to_signed(secret)
        # Flip a character in the middle
        tampered = signed[:-5] + ("X" if signed[-5] != "X" else "Y") + signed[-4:]
        restored = SessionToken.from_signed(tampered, secret, max_age_seconds=86400)
        assert restored is None

    def test_wrong_secret_returns_none(self) -> None:
        token = SessionToken(user_id=1, exp=int(time.time()) + 3600)
        signed = token.to_signed(Settings.generate_session_secret())
        wrong = Settings.generate_session_secret()
        restored = SessionToken.from_signed(signed, wrong, max_age_seconds=86400)
        assert restored is None


class TestSessionCookie:
    """Cookie set / clear smoke tests (response object is a SimpleNamespace mock)."""

    def test_create_session_cookie(self) -> None:
        from types import SimpleNamespace

        response = SimpleNamespace()
        response.set_cookie_calls: list[dict] = []
        response.delete_cookie_calls: list = []

        def fake_set_cookie(**kwargs: object) -> None:
            response.set_cookie_calls.append(kwargs)

        def fake_delete_cookie(**kwargs: object) -> None:
            response.delete_cookie_calls.append(kwargs)

        response.set_cookie = fake_set_cookie  # type: ignore[method-assign]
        response.delete_cookie = fake_delete_cookie  # type: ignore[method-assign]

        from app.core.security import settings

        original_secret = settings.session_secret
        original_https = settings.require_https
        try:
            settings.session_secret = Settings.generate_session_secret()
            settings.require_https = False
            create_session_cookie(response, user_id=123)
        finally:
            settings.session_secret = original_secret
            settings.require_https = original_https

        assert len(response.set_cookie_calls) == 1
        call = response.set_cookie_calls[0]
        assert call["key"] == "pulseorder_session"
        assert call["httponly"] is True
        assert call["samesite"] == "lax"
        assert call["secure"] is False

    def test_clear_session_cookie(self) -> None:
        from types import SimpleNamespace

        response = SimpleNamespace()
        response.delete_cookie_calls: list = []

        def fake_delete_cookie(**kwargs: object) -> None:
            response.delete_cookie_calls.append(kwargs)

        response.delete_cookie = fake_delete_cookie  # type: ignore[method-assign]

        clear_session_cookie(response)

        # `clear_session_cookie` always passes `domain` (via
        # `_extract_cookie_domain`), even when it resolves to `None` (no
        # `request` was passed here). This is deliberate: a cookie set
        # with an explicit domain must be deleted with the SAME domain
        # or the browser leaves the original cookie in place. See
        # `app/core/security.py::_extract_cookie_domain` docstring.
        assert response.delete_cookie_calls == [
            {"key": "pulseorder_session", "path": "/", "domain": None}
        ]
