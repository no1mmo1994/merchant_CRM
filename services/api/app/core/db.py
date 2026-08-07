"""SQLModel database engine, session factory, and init helper."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
import logging

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
    # We pull the package's public exports rather than listing each
    # class so adding a new model file doesn't require touching init_db.
    from app.models import (  # noqa: F401  (import side-effect: metadata registration)
        AuditLog,
        OrderSnapshot,
        Store,
        StoreApiKey,
        User,
    )

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

    # ── Column-level migrations ────────────────────────────────────────
    # ``metadata.create_all`` only creates missing *tables*; it never
    # ALTERs existing tables to add new columns. When the round-5
    # work added ``Store.region`` to the model, fresh installs got the
    # column via create_all but existing production DBs (where
    # ``stores`` already existed from earlier rounds) crashed on every
    # scheduler tick with ``no such column: stores.region``. This loop
    # reconciles the live SQLite schema against the SQLModel
    # definition and ALTERs the gap.
    #
    # Idempotent: ``inspect()`` is read first, so on the next startup
    # the column already exists and we skip. SQLite's ``ALTER TABLE
    # ADD COLUMN`` is itself idempotent only if guarded by the
    # existence check, hence the surrounding try/except for the
    # rare race where two processes both decide to add at once.
    _migrate_missing_columns(_engine)


# Re-export engine for direct use in tests.
engine = _engine


def _migrate_missing_columns(_engine) -> None:  # noqa: ANN001
    """Reconcile live DB columns with SQLModel metadata.

    For each table that exists in both the live DB and SQLModel
    metadata, compare the live column set against the model
    definition. For any column present in the model but missing
    in the DB, emit ``ALTER TABLE … ADD COLUMN``. This is the
    minimal column-level migration primitive we need; future
    rounds can extend it with type/rename/backfill steps.

    Round-5 special case: when ``stores.region`` is added to an
    older DB that already has ``stores.address``, immediately
    backfill ``region`` from ``address`` via
    ``app.core.region.extract_city`` so the partner API's
    ``source`` field surfaces a non-empty label without waiting
    for the 24h scheduler.

    The whole routine is best-effort: an OperationalError on
    ALTER (e.g. concurrent process already added the column) is
    swallowed and logged. A failed migration must NEVER crash
    uvicorn startup — the existing scheduler will retry the
    address-fetch on its next tick.
    """
    from sqlalchemy import inspect as _sa_inspect, text as _sa_text
    from sqlmodel import SQLModel as _SQLModel

    insp = _sa_inspect(_engine)
    live_tables = set(insp.get_table_names())
    log = logging.getLogger("pulseorder.db")

    for tbl in _SQLModel.metadata.sorted_tables:
        if tbl.name not in live_tables:
            continue  # missing-table path is handled by create_all above
        live_cols = {c["name"] for c in insp.get_columns(tbl.name)}
        for col in tbl.columns:
            if col.name in live_cols:
                continue
            # SQLite ALTER TABLE ADD COLUMN supports a tiny subset of
            # types. Strip server_default / notnull / FKs and emit a
            # plain nullable VARCHAR. Backfill (if any) runs after.
            type_str = _sqlite_type_for(col)
            ddl = f'ALTER TABLE "{tbl.name}" ADD COLUMN "{col.name}" {type_str}'
            try:
                with _engine.begin() as conn:
                    conn.execute(_sa_text(ddl))
                log.warning(
                    "db_migration: added %s.%s (%s)",
                    tbl.name, col.name, type_str,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "db_migration: failed to add %s.%s — %s",
                    tbl.name, col.name, exc,
                )

    # Round-5 backfill: stores.region was added after stores.address,
    # so any pre-existing Store rows have a populated ``address`` but
    # an empty ``region``. Re-derive the region now so the partner
    # API's ``source`` field surfaces a city immediately rather than
    # waiting up to 24h for ``store_sync`` to write it.
    if (
        "stores" in live_tables
        and "region" in {c["name"] for c in insp.get_columns("stores")}
    ):
        try:
            from app.core.region import extract_city
            with _engine.begin() as conn:
                rows = conn.execute(_sa_text(
                    "SELECT id, address FROM stores "
                    "WHERE region = '' OR region IS NULL"
                )).fetchall()
                for store_id, address in rows:
                    new_region = extract_city(address or "")
                    if new_region:
                        conn.execute(_sa_text(
                            "UPDATE stores SET region = :r WHERE id = :id"
                        ), {"r": new_region, "id": store_id})
                if rows:
                    log.warning(
                        "db_migration: backfilled region for %d store(s)",
                        len(rows),
                    )
        except Exception as exc:  # noqa: BLE001
            log.warning("db_migration: region backfill failed — %s", exc)


def _sqlite_type_for(col) -> str:  # noqa: ANN001
    """Render a SQLAlchemy Column as the minimal SQLite type string.

    SQLite only really stores TEXT / INTEGER / REAL / BLOB / NUMERIC;
    SQLAlchemy's ``VARCHAR(N)`` is fine but a generic ``TEXT`` keeps
    ALTER TABLE portable and avoids the type-affinity gotchas (e.g.
    VARCHAR(255) on a numeric column). The Python-side type
    coercion still works because SQLModel models expose Python
    ``str`` / ``int`` / ``datetime`` regardless of the DB type.
    """
    from sqlalchemy import (
        Integer,
        String,
        Text,
        Float,
        Boolean,
        DateTime,
        Date,
        Time,
        LargeBinary,
    )
    py_type = col.type
    if isinstance(py_type, (String, Text)):
        return "TEXT"
    if isinstance(py_type, Integer):
        return "INTEGER"
    if isinstance(py_type, Float):
        return "REAL"
    if isinstance(py_type, Boolean):
        return "INTEGER"
    if isinstance(py_type, (DateTime, Date, Time)):
        return "TEXT"
    if isinstance(py_type, LargeBinary):
        return "BLOB"
    return "TEXT"
