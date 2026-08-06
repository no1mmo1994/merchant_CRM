"""OrderArchive — frozen-in-time snapshot of each order's customer detail.

Persisted at first sight by the 30-second order-polling cron
(``app.core.scheduler._poll_one_store``). The whole point of this
table is to make customer info survive Grab's state transitions:

  * the preparing queue carries ``eater.name`` + ``mobileNumber`` +
    ``address`` + ``comment`` + full item breakdown;
  * once the order moves to ``ORDER_COMPLETED`` / ``ORDER_CANCELLED``,
    Grab's daily-reports endpoint only returns summary fields
    (``displayID`` + ``priceDisplay`` + ``updatedAt``). The
    detail endpoint often WAF-rejects old orders, so the merchant
    would otherwise see blank customer info on every completed /
    cancelled row.

By snapshotting the full detail at first sight, the dashboard's
``/api/orders/history`` route can hydrate ``OrderDetailLite`` from
this table instead of fanning out a per-order detail call that
might fail.

Rows are keyed on ``(store_id, order_id)`` — each store's order id
uniquely identifies one order. The first time the cron sees an
order it inserts a row; subsequent polls (while the order is still
in the preparing queue) just refresh ``state`` + ``last_seen_at``.
Once the order leaves the preparing queue the row stays — that's
the whole point.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Column, Text
from sqlmodel import Field, SQLModel


class OrderArchive(SQLModel, table=True):
    """Persisted snapshot of one order's full detail (eater + items + fare).

    One row per ``(store_id, order_id)`` pair; the ``detail_json`` blob
    stores the raw Grab detail payload so the router can hydrate
    ``OrderDetailLite`` straight from the archive without hitting
    Grab's per-order detail endpoint (which often 400s for orders
    that have already left the preparing queue).
    """

    __tablename__ = "order_archives"

    id: int | None = Field(default=None, primary_key=True)
    store_id: int = Field(foreign_key="stores.id", index=True)
    merchant_id: str = Field(index=True)
    # Composite uniqueness — every Grab order id is unique within a
    # single merchant store. ``unique=True`` + ``index=True`` gives
    # both an integrity constraint and a fast lookup-by-id index.
    order_id: str = Field(index=True, unique=True)
    display_id: str = Field(default="", index=True)
    state: str = Field(default="")
    # ``Text`` rather than ``JSON`` so we can keep the exact wire
    # shape (Pydantic ``OrderDetail.model_dump_json`` output) without
    # a second SQLAlchemy JSON column type that some SQLite builds
    # refuse to create via ``SQLModel.metadata.create_all``.
    detail_json: str = Field(default="", sa_column=Column(Text))
    first_seen_at: datetime = Field(default_factory=datetime.utcnow)
    last_seen_at: datetime = Field(default_factory=datetime.utcnow)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def detail_payload(self) -> dict[str, Any]:
        """Parse ``detail_json`` back into a dict (empty dict on failure).

        The router only needs the eater / item_info / fare / times
        block — the same shape ``OrderDetailLite.from_raw`` already
        handles. We return a plain dict instead of an
        ``OrderDetailLite`` instance so the router can decide
        whether to project via ``from_raw`` or via ``model_validate``.
        """
        import json

        if not self.detail_json:
            return {}
        try:
            parsed = json.loads(self.detail_json)
        except (ValueError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
