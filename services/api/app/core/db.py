"""SQLModel database engine, session factory, and init helper."""

from __future__ import annotations

from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

from app.core.config import settings

# The engine is built once at import time.
# SQLite is the only supported backend in Phase 03.
#
# connect_args={"check_same_thread": False} is required for FastAPI's
# synchronous dependency injection model when running with uvicorn's
# threaded mode (the default on Windows).
_engine = create_engine(
    settings.database_url,
    echo=False,
    connect_args={"check_same_thread": False},
    # Pool sized for the dashboard's per-page fan-out: `/api/auth/me`,
    # `/api/stores`, `/api/stores/:id/info`, `/api/menu`,
    # `/api/modifiers/groups` can all fire on a single page mount. With
    # the default pool_size=5 the pool exhausts under typical load;
    # bumped to 10 with overflow 20 (= 30 total) so concurrent page
    # loads always have a free connection. `pool_timeout=10` (down
    # from the 30s default) ensures a saturated pool surfaces as a
    # fast 5xx instead of a 30s hang on every queued request.
    pool_size=10,
    max_overflow=20,
    pool_timeout=10,
)


def get_session():
    """FastAPI dependency — yields a SQLModel Session, auto-closes on exit.

    Generator dependency (uses `yield`) so FastAPI's dependency-injection
    framework runs the `finally` block after every request, even on
    exception. Critical under concurrent load: a non-generator
    `get_session()` accumulates leaked sessions in the SQLite connection
    pool until `QueuePool limit of size 5 overflow 10 reached, … timed
    out waiting for connection` fires after ~15 concurrent requests,
    hanging every subsequent `require_user` route for the 30s pool
    timeout. That manifested as the dashboard stuck on
    "Đang xác thực phiên đăng nhập…" after navigation to pages that
    fan out parallel calls (the modifiers page added one more).

    Tests override this with a fixture-provided Session by patching
    `app.core.db.get_session`.
    """
    session = Session(_engine)
    try:
        yield session
    finally:
        session.close()


def init_db() -> None:
    """Create all tables and ensure the data directory exists.

    Under uvicorn --reload, the reloader subprocess and the server child
    both run lifespan; with SQLite + a file DB they can race on
    CREATE TABLE → "table already exists".  We avoid the race by
    short-circuiting when the users table is already present.
    """
    # Ensure ./data/ exists when using the default sqlite:///./data/grab.db path.
    db_url = settings.database_url
    if db_url.startswith("sqlite"):
        rel_path = db_url.removeprefix("sqlite:///").lstrip("/")
        data_dir = Path(rel_path).parent
        data_dir.mkdir(parents=True, exist_ok=True)

    # Import all models so SQLModel.metadata registers every table.
    from app.models import AuditLog, Store, User  # noqa: F401

    # Skip if already initialised — avoids CREATE TABLE races under
    # uvicorn --reload (parent reloader + child server both run lifespan).
    from sqlmodel import inspect
    if inspect(_engine).get_table_names():
        return

    SQLModel.metadata.create_all(_engine)


# Re-export engine for direct use in tests.
engine = _engine
