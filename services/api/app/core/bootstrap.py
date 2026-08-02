"""First-run safety net for the .env file.

When `pnpm dev` is run on a fresh clone, services/api/.env doesn't
exist yet. PulseOrder's secrets actually live at the repo-root `.env`,
which `app.core.config._resolve_env_file()` already locates. This
module is a **secondary safety net**: if *neither* `.env` exists, we
copy `.env.example` to `services/api/.env` and inject freshly-
generated Fernet key + session secret so a fresh clone "just works".

We deliberately scope this to local mode. Deploy mode must fail loud
when secrets are missing so the operator notices, instead of silently
generating and discarding them on every restart.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.core.config import Settings

log = logging.getLogger("pulseorder.bootstrap")


def _api_dir() -> Path:
    """Locate services/api/ from this file (app/core/bootstrap.py → 3 parents up)."""
    return Path(__file__).resolve().parents[3]


def _maybe_create_env() -> None:
    """If local mode and a Fernet key can't be loaded from any .env,
    copy `.env.example` to `services/api/.env` and inject fresh keys."""
    api_dir = _api_dir()
    example = api_dir / ".env.example"
    target = api_dir / ".env"

    # Quick probe: what does Settings see if we instantiate it now?
    probe = Settings()
    if probe.app_mode != "local":
        return  # deploy mode → never auto-generate
    if probe.token_encryption_key:
        return  # already configured (likely via repo-root .env)

    if not example.exists():
        log.warning(
            "bootstrap: %s not found; cannot auto-generate %s. "
            "Create it manually with a valid TOKEN_ENCRYPTION_KEY.",
            example, target,
        )
        return

    if not target.exists():
        target.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        log.info("bootstrap: copied %s → %s", example.name, target.name)

    lines = target.read_text(encoding="utf-8").splitlines()
    patched: list[str] = []
    for line in lines:
        if line.startswith("TOKEN_ENCRYPTION_KEY="):
            patched.append(f"TOKEN_ENCRYPTION_KEY={Settings.generate_fernet_key()}")
        elif line.startswith("SESSION_SECRET="):
            patched.append(f"SESSION_SECRET={Settings.generate_session_secret()}")
        else:
            patched.append(line)
    target.write_text("\n".join(patched) + "\n", encoding="utf-8")
    log.info("bootstrap: wrote fresh TOKEN_ENCRYPTION_KEY + SESSION_SECRET to %s", target)


def ensure_local_secrets() -> None:
    """Entry point used from app startup. Idempotent."""
    _maybe_create_env()