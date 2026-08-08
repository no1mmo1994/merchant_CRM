"""PulseOrder FastAPI entry point — Phase 11 fully wired.

Run:
    uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
    # or via console script:
    uv run grab-api

Endpoints:
    GET  /                service banner
    GET  /api/health      liveness probe
    GET  /docs            OpenAPI Swagger UI
    POST /api/auth/login  3-step Grab login (rate-limited)
    POST /api/auth/logout clear session
    GET  /api/auth/me     current user + stores
    POST /api/auth/refresh-token  refresh Grab auth token
    GET  /api/stores      list user's stores
    GET  /api/stores/{id} store detail + business attrs
    POST /api/stores/select  set active store cookie
    DELETE /api/stores/{id}  danger zone — delete store
    GET  /api/menu        full Grab menu
    POST /api/categories  create category
    DELETE /api/categories/{id}  delete category
    PUT  /api/categories/sort  reorder categories
    POST /api/items/upload-image  upload item image
    POST /api/items       create menu item
    POST /api/modifiers/verify  verify modifier
    POST /api/modifiers/groups  create modifier group
    GET  /api/finance/summary   Grab financial summary (date range)
    GET  /api/audit       paginated audit log
"""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from starlette.responses import JSONResponse

from app import __version__
from app.core.bootstrap import ensure_local_secrets
from app.core.config import settings
from app.core.db import init_db
from app.core.limiter import limiter
from app.core.scheduler import start_scheduler, stop_scheduler
from app.core.security import TokenEncryptionNotConfigured
from app.routers import (  # noqa: F401  (routers self-register)
    audit_router,
    auth_router,
    categories_router,
    customers_router,
    finance_router,
    items_router,
    marketing_router,
    menu_router,
    modifiers_router,
    orders_router,
    partner_router,
    stores_router,
    tiers_router,
)

# Module-level alias so tests can patch `app.main.limiter`
__all__ = ["app", "create_app", "limiter", "main"]

log = logging.getLogger("pulseorder.main")


def _rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Return a clean JSON error when a rate limit is breached."""
    return JSONResponse(
        status_code=429,
        content={"detail": f"Rate limit exceeded: {exc.detail}"},
    )


def _token_encryption_misconfigured_handler(
    request: Request, exc: TokenEncryptionNotConfigured
) -> JSONResponse:
    """Surface a missing FERNET_KEY as a structured 503 instead of a 500.

    Defence in depth: `ensure_local_secrets()` runs at lifespan start
    and writes a fresh key on a fresh clone, so this handler only fires
    if the operator deletes the .env *while* the server is running, or
    if deploy mode ran without keys. In both cases, the right response
    is "service unavailable until configured", with a hint pointing at
    the missing key — not a useless 21-byte 500.
    """
    log.exception("Token encryption invoked without configured key: %s", exc)
    return JSONResponse(
        status_code=503,
        content={
            "detail": {
                "code": "encryption_key_missing",
                "message": (
                    "PulseOrder cannot encrypt or decrypt tokens right now: "
                    "the Fernet key is not configured on the server."
                ),
                "hint": (
                    "An operator needs to set TOKEN_ENCRYPTION_KEY in "
                    ".env (run `python -c \"from app.core.config import "
                    "Settings; print(Settings.generate_fernet_key())\"` "
                    "to generate one) and restart the API."
                ),
                "fields": [],
                "request_id": None,
            }
        },
    )


# ── Lifespan ─────────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise DB on startup; print local-mode banner; start scheduler.

    Bootstrap order:
      1. `ensure_local_secrets()` may write fresh keys to
         services/api/.env on a fresh clone. It returns nothing; if it
         wrote anything, we need to rebind our module-level `settings`
         reference so the freshly-populated keys flow into routers,
         core.security, etc.
    """
    import app.core.config as _config
    pre_token = settings.token_encryption_key
    ensure_local_secrets()
    post_token = _config.Settings().token_encryption_key  # freshly-read
    if post_token and post_token != pre_token:
        # Bootstrap wrote a new .env: rebind the singleton so the rest
        # of the app sees the populated keys.
        _config.settings = _config.Settings()
    init_db()
    if settings.app_mode == "local":
        banner = (
            "\n"
            "  ╔══════════════════════════════════════════════════════════╗\n"
            "  ║  WARNING: PulseOrder running in LOCAL mode                ║\n"
            "  ║  Do NOT use this configuration in production.            ║\n"
            "  ╚══════════════════════════════════════════════════════════╝\n"
        )
        print(banner, file=sys.stderr)
    scheduler = start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()


# ── App factory ──────────────────────────────────────────────────────────────────


def create_app() -> FastAPI:
    app = FastAPI(
        title="PulseOrder API",
        description="Backend for the PulseOrder Grab Merchant dashboard.",
        version=__version__,
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
        redirect_slashes=False,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # SlowAPI state + error handler
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_exception_handler(
        TokenEncryptionNotConfigured, _token_encryption_misconfigured_handler
    )

    # Routers
    app.include_router(auth_router)
    app.include_router(stores_router)
    app.include_router(menu_router)
    app.include_router(marketing_router)
    app.include_router(tiers_router)
    app.include_router(categories_router)
    app.include_router(items_router)
    app.include_router(modifiers_router)
    app.include_router(finance_router)
    app.include_router(orders_router)
    app.include_router(customers_router)
    app.include_router(audit_router)
    app.include_router(partner_router)

    # ── Static endpoints ──────────────────────────────────────────────────────────
    @app.get("/")
    def root() -> dict[str, str]:
        return {
            "service": "PulseOrder API",
            "version": __version__,
            "status": "ok",
        }

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app


app = create_app()


# ── Console entry point ──────────────────────────────────────────────────────────


def main() -> None:
    """`uv run grab-api` / `python -m app.main` entry point."""
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.app_mode == "local",
    )


if __name__ == "__main__":
    main()
