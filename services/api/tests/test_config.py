"""Tests for app.core.config (Settings)."""

from __future__ import annotations

import pytest

from app.core.config import Settings


class TestDefaultSettings:
    """Default values put settings in local mode."""

    def test_local_mode_by_default(self) -> None:
        s = Settings()
        assert s.app_mode == "local"
        assert s.is_local_mode is True
        assert s.is_deploy_mode is False

    def test_default_api_host_local(self) -> None:
        s = Settings()
        assert s.api_host == "127.0.0.1"

    def test_default_require_https_false(self) -> None:
        s = Settings()
        assert s.require_https is False

    def test_default_database_url(self) -> None:
        s = Settings()
        assert s.database_url == "sqlite:///./data/grab.db"

    def test_default_cors_origins(self) -> None:
        s = Settings()
        assert "http://localhost:3000" in s.cors_origins
        assert "http://127.0.0.1:3000" in s.cors_origins


class TestKeyGenerators:
    """Static helpers produce valid output."""

    def test_generate_fernet_key_length(self) -> None:
        key = Settings.generate_fernet_key()
        assert isinstance(key, str)
        assert len(key) == 44  # Fernet urlsafe-base64 keys are always 44 chars
        # Verify it looks like a Fernet key (URL-safe base64 chars: alnum + -_=)
        assert all(c.isalnum() or c in "-_=" for c in key)

    def test_generate_session_secret_length(self) -> None:
        secret = Settings.generate_session_secret()
        assert isinstance(secret, str)
        assert len(secret) >= 32
        # URL-safe chars only
        assert all(c.isalnum() or c in "-_" for c in secret)

    def test_generate_fernet_key_usable(self) -> None:
        from cryptography.fernet import Fernet

        key = Settings.generate_fernet_key()
        f = Fernet(key.encode("utf-8"))
        encrypted = f.encrypt(b"test")
        assert f.decrypt(encrypted) == b"test"


class TestDeployModeValidator:
    """Deploy mode requires session_secret and admin_password_hash."""

    def test_deploy_rejects_missing_session_secret(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Settings() reads .env at module load; explicitly clear the env-file
        # values for this test so the validator sees an empty field.
        monkeypatch.setenv("APP_MODE", "deploy")
        monkeypatch.setenv("ADMIN_PASSWORD_HASH", "some_hash")
        monkeypatch.delenv("SESSION_SECRET", raising=False)
        monkeypatch.delenv("TOKEN_ENCRYPTION_KEY", raising=False)
        with pytest.raises(ValueError) as exc_info:
            Settings(_env_file=None)
        assert "session_secret" in str(exc_info.value)

    def test_deploy_rejects_missing_admin_password_hash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("APP_MODE", "deploy")
        monkeypatch.setenv("SESSION_SECRET", "some_secret")
        monkeypatch.delenv("ADMIN_PASSWORD_HASH", raising=False)
        monkeypatch.delenv("TOKEN_ENCRYPTION_KEY", raising=False)
        with pytest.raises(ValueError) as exc_info:
            Settings(_env_file=None)
        assert "admin_password_hash" in str(exc_info.value)

    def test_deploy_accepts_both_fields(self) -> None:
        s = Settings(
            app_mode="deploy",
            session_secret="a" * 40,
            admin_password_hash="$2b$12$dummyhash",
        )
        assert s.is_deploy_mode is True

    def test_deploy_auto_sets_api_host_to_0_0_0_0(self) -> None:
        s = Settings(
            app_mode="deploy",
            session_secret="a" * 40,
            admin_password_hash="$2b$12$dummyhash",
        )
        assert s.api_host == "0.0.0.0"

    def test_deploy_auto_sets_require_https_true(self) -> None:
        s = Settings(
            app_mode="deploy",
            session_secret="a" * 40,
            admin_password_hash="$2b$12$dummyhash",
        )
        assert s.require_https is True

    def test_deploy_api_port_preserved(self) -> None:
        s = Settings(
            app_mode="deploy",
            session_secret="a" * 40,
            admin_password_hash="$2b$12$dummyhash",
            api_port=9000,
        )
        assert s.api_port == 9000
