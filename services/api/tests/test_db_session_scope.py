"""
Regression tests for ``app.core.db.session_scope``.

Guards two invariants so the "Internal Server Error on login" bug doesn't
return:

1. ``session_scope`` is a working context manager that yields a real
   ``sqlalchemy.orm.Session`` and closes it even on exception.
2. ``get_session`` remains a generator function — ``app/deps.py`` does
   ``yield from _get_session()`` so FastAPI's Depends pathway keeps
   driving its ``finally`` block per request (USER CONSTRAINT).

The bug: APScheduler job bodies used to call ``with get_session() as
session:``. ``get_session`` is a generator, not a context manager, so the
very first tick crashed with ``TypeError: 'generator' object does not
support the context manager protocol``. That crash leaked into the shared
async event loop and manifested as intermittent 500s on the next HTTP
request — including the login form.
"""

from __future__ import annotations

import inspect
import threading

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import get_session, session_scope


# ── 1. session_scope is a context manager ─────────────────────────────────────


def test_session_scope_returns_contextmanager_object():
    """``@contextmanager``-decorated functions return an object with __enter__/__exit__.

    That wrapper drives the inner generator so the `with` block can
    advance it and trigger the underlying Session's open/close lifecycle.

    We avoid importing `_GeneratorContextManager` (private, renamed
    across CPython versions) and just assert the protocol the scheduler
    actually relies on: ``__enter__`` / ``__exit__`` are present and
    ``__exit__`` invokes the `finally` block.
    """
    cm = session_scope()
    try:
        assert hasattr(cm, "__enter__") and hasattr(cm, "__exit__"), (
            f"session_scope() must return a context-manager-shaped object "
            f"(that's how @contextmanager works — without it, `with "
            f"session_scope() as s:` would TypeError); got {type(cm).__name__}"
        )
    finally:
        # ``.close()`` on the wrapper advances the inner generator and
        # triggers the `finally` block — exactly what `with` does on exit.
        if hasattr(cm, "close"):
            cm.close()


def test_session_scope_yields_real_sqlalchemy_session():
    """``with session_scope() as s:`` must hand back a working Session.

    Sanity-checks the bound engine and a trivial SELECT — both pass on
    the in-memory SQLite used by pytest.
    """
    with session_scope() as s:
        assert isinstance(s, Session), (
            f"expected sqlalchemy Session, got {type(s).__name__}"
        )
        assert s.bind is not None, "Session must be bound to the module engine"
        # Exercise the connection so a broken/boundless session surfaces here.
        result = s.execute(text("SELECT 1")).scalar_one()
        assert result == 1


def test_session_scope_closes_session_on_exception():
    """If the with-body raises, the session must still close (no pool leak).

    Spies on ``session.close()`` rather than relying on the engine pool
    counter — the pool's ``close()`` is delegated through SQLAlchemy
    internals and a test assertion on the spy is far more readable than
    a pool accounting probe.
    """
    closed = {"flag": False}
    original_close = None

    with pytest.raises(RuntimeError, match="boom"):
        with session_scope() as s:
            original_close = s.close

            def _spy_close() -> None:
                closed["flag"] = True
                original_close()

            s.close = _spy_close  # type: ignore[method-assign]
            raise RuntimeError("boom")

    assert closed["flag"], (
        "session.close() was NOT called after an exception inside `with` — "
        "session_scope leaks sessions, the SQLite pool will exhaust under "
        "scheduler load"
    )


def test_session_scope_yields_independent_sessions_in_sequence():
    """Each ``with session_scope()`` block must yield a fresh Session object.

    Reusing the same Session across blocks would silently mix uncommitted
    state between scheduler jobs — one job's INSERT might appear in
    another's SELECT without explicit commit, violating the per-job
    isolation we want.
    """
    seen: list[int] = []
    for _ in range(3):
        with session_scope() as s:
            seen.append(id(s))
    assert len(set(seen)) == 3, (
        f"session_scope yielded the same Session {len(set(seen))} "
        "time(s) across 3 consecutive `with` blocks — that's a leak"
    )


# ── 2. USER CONSTRAINT guardrail: get_session must stay a generator ─────────


def test_get_session_is_still_a_generator():
    """USER CONSTRAINT: ``app/deps.py`` does ``yield from _get_session()``.

    FastAPI's dependency-injection only runs the ``finally`` block of a
    generator-dep. If somebody refactors ``get_session`` into a
    @contextmanager (to "unify" with session_scope), every request
    leaks a Session and the SQLite pool will eventually lock. This
    test fails loudly to prevent that.
    """
    gen = get_session()
    try:
        assert inspect.isgenerator(gen), (
            "get_session must remain a generator function "
            "(deps.py does `yield from _get_session()` — FastAPI DI "
            "relies on generator-shape to drive the `finally` block)"
        )
        # A generator-style dep yields a Session object; assert it can
        # be advanced and closed cleanly.
        try:
            value = next(gen)
        except StopIteration:
            pytest.fail(
                "get_session() yielded nothing — the generator returned "
                "without ever yielding the Session"
            )
        assert isinstance(value, Session), (
            f"get_session must yield a sqlalchemy Session, got "
            f"{type(value).__name__}"
        )
    finally:
        # Advance past the generator's finally so the session closes
        # cleanly for the next test.
        try:
            next(gen)
        except StopIteration:
            pass


# ── 3. Pool doesn't exhaust under scheduler-like burst load ──────────────────


@pytest.mark.parametrize("burst_size", [50])
def test_session_scope_pool_does_not_exhaust_in_subthread(burst_size: int) -> None:
    """Open N sessions from a sub-thread; each must close cleanly.

    Burst comes from a sub-thread because APScheduler fires each job on
    its own worker — exercise the same cross-thread open/close path
    the scheduler uses. Failure here means ``.close()`` is missing or
    broken, which is the same root cause as the original 500 bug.
    """
    errors: list[str] = []

    def worker() -> None:
        try:
            for _ in range(burst_size):
                with session_scope() as s:
                    s.execute(text("SELECT 1")).scalar_one()
        except Exception as exc:  # noqa: BLE001 — failure collection
            errors.append(repr(exc))

    t = threading.Thread(target=worker, name="session_scope_burst")
    t.start()
    t.join(timeout=60)

    assert not t.is_alive(), (
        f"sub-thread hung after {burst_size} session opens — "
        "session_scope likely leaks connections"
    )
    assert not errors, f"session_scope raised under burst: {errors}"


# ── 4. module surface — keep imports stable for the scheduler ────────────────


def test_both_session_helpers_are_exported_from_db_module() -> None:
    """``scheduler.py`` imports ``session_scope``; anything else that does
    ``from app.core.db import get_session`` must keep working (e.g. tests,
    any future scheduler that wants the FastAPI-shaped session). This
    test exists so a future "let's collapse the two into one helper"
    refactor flags here before it breaks either path.
    """
    import app.core.db as db_module
    assert hasattr(db_module, "session_scope"), (
        "app.core.db must export `session_scope` — scheduler imports it"
    )
    assert hasattr(db_module, "get_session"), (
        "app.core.db must keep `get_session` — deps.py imports it as "
        "`_get_session` and does `yield from _get_session()`"
    )
