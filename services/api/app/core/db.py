"""SQLModel database engine, session factory, and init helper."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

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


@contextmanager
def session_scope() -> Iterator["Session"]:
    """Yield a fresh Session bound to the module-level engine; close on exit.

    Use this in non-FastAPI callers — background jobs, APScheduler tasks,
    one-shot CLI scripts. FastAPI request handlers MUST keep using
    ``get_session`` (the generator above) because ``app/deps.py``
    depends on it via ``yield from _get_session()``. Don't replace one
    with the other: ``get_session`` is generator-shaped so FastAPI's
    dependency-injection can drive its ``finally``; ``session_scope`` is
    contextmanager-shaped so ``with`` blocks can drive theirs.

    Why both exist: APScheduler job bodies used to call ``with
    get_session() as session:``. ``get_session`` is a generator, not a
    context manager, so the very first tick crashed with
    ``TypeError: 'generator' object does not support the context manager
    protocol``. That crash leaked into the shared async event loop and
    manifested as intermittent 500s on the next HTTP request — including
    the login form, which the operator saw as "Internal Server Error"
    even though the login router itself was untouched.
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
    from app.models import AuditLog, OrderSnapshot, Store, User  # noqa: F401

    # Skip full re-create if already initialised — avoids CREATE TABLE
    # races under uvicorn --reload (parent reloader + child server
    # both run lifespan). We still need `create_all` to apply the
    # delta when new tables (e.g. `order_snapshots`) were added by a
    # later model file on an existing DB, so always run it — it's a
    # no-op for tables that already exist.
    from sqlmodel import inspect, SQLModel as _SQLModel
    # Use SQLAlchemy's `inspect(...)` to enumerate what already exists,
    # then only create the tables that are missing. SQLModel.metadata
    # `.create_all(checkfirst=True)` does *not* reliably no-op when the
    # metadata is collected across multiple model files in this
    # SQLAlchemy version — it emits `CREATE TABLE` for already-existing
    # tables and the SQLite engine raises `OperationalError: table
    # ... already exists` on the first collision. Filtering the
    # `tables=` argument avoids the race AND works under uvicorn
    # --reload (parent reloader + child server both running lifespan).
    existing = set(inspect(_engine).get_table_names())
    missing_tables = [
        tbl
        for tbl in _SQLModel.metadata.sorted_tables
        if tbl.name not in existing
    ]
    if missing_tables:
        _SQLModel.metadata.create_all(
            _engine, tables=missing_tables, checkfirst=True
        )


# Re-export engine for direct use in tests.
engine = _engine
