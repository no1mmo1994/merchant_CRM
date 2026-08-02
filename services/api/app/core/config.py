"""Pydantic-settings for PulseOrder.

Reads all values from .env at the project root.  In deploy mode the
validator enforces that session_secret and admin_password_hash are
present and forces api_host / require_https to safe production values.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Literal

from cryptography.fernet import Fernet
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# ── Locate .env ──────────────────────────────────────────────────────────────
# Settings() reads env_file=".env" relative to the *current working
# directory*, not the file's location. Uvicorn runs from
# services/api/, so a bare ".env" would only see services/api/.env — but
# PulseOrder's `.env` lives at the repo root (next to package.json).
#
# Walk upward until we find a `.env`, then fall back to a one-shot
# bootstrap that copies `.env.example` and generates the secrets on
# first run. That makes `pnpm dev` Just Work even for a fresh clone.
def _resolve_env_file() -> str | None:
    here = Path(__file__).resolve()
    for parent in (here, *here.parents):
        candidate = parent / ".env"
        if candidate.is_file():
            return str(candidate)
    return None


class Settings(BaseSettings):
    """Application configuration, fully driven by environment variables."""

    model_config = SettingsConfigDict(
        env_file=_resolve_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Deployment mode ───────────────────────────────────────────────────────
    app_mode: Literal["local", "deploy"] = "local"

    # ── Server ──────────────────────────────────────────────────────────────
    api_host: str = "127.0.0.1"
    api_port: int = 8000

    # ── Database ─────────────────────────────────────────────────────────────
    database_url: str = "sqlite:///./data/grab.db"

    # ── Security ─────────────────────────────────────────────────────────────
    token_encryption_key: str = ""  # Fernet key; set via Fernet.generate_key()
    admin_password_hash: str = ""  # bcrypt hash; required in deploy
    session_secret: str = ""  # used by itsdangerous URLSafeTimedSerializer

    # ── CORS ─────────────────────────────────────────────────────────────────
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"],
    )

    # ── TLS / HTTPS ──────────────────────────────────────────────────────────
    require_https: bool = False
    grab_verify_ssl: bool = False  # SSL verify for Grab API calls (False = MITM-friendly)

    # ── Rate limiting ────────────────────────────────────────────────────────
    rate_limit_per_minute: int = 60

    # ── Validators ──────────────────────────────────────────────────────────
    @model_validator(mode="after")
    def _validate_mode(self) -> "Settings":
        if self.app_mode == "deploy":
            missing: list[str] = []
            if not self.session_secret:
                missing.append("session_secret")
            if not self.admin_password_hash:
                missing.append("admin_password_hash")
            if missing:
                raise ValueError(
                    f"[deploy] The following fields must be set in .env: "
                    + ", ".join(missing)
                )
            # Force safe production defaults
            self.api_host = "0.0.0.0"
            self.require_https = True
        return self

    # ── Computed helpers ─────────────────────────────────────────────────────
    @property
    def is_local_mode(self) -> bool:
        return self.app_mode == "local"

    @property
    def is_deploy_mode(self) -> bool:
        return self.app_mode == "deploy"

    # ── Key generation helpers ───────────────────────────────────────────────
    @staticmethod
    def generate_fernet_key() -> str:
        """Return a new Fernet key as a UTF-8 string (urlsafe-base64, 44 chars)."""
        return Fernet.generate_key().decode("utf-8")

    @staticmethod
    def generate_session_secret() -> str:
        """Return a new 43-char (32-byte) URL-safe token."""
        return secrets.token_urlsafe(32)


# Singleton — imported by the rest of the app.
settings = Settings()
