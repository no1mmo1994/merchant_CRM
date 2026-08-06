"""OrderSnapshot — last-poll result of the 30-second order cron.

Stores the per-store result of each "đã chạy get lại đơn" run so the
dashboard can show a banner like:

    ✅ Đã chạy get lại đơn lúc 14:42 — tìm thấy 2 đơn mới
    ⚠️ Đã chạy get lại đơn lúc 14:42 — chưa tìm thấy đơn

One row per store (we keep the latest run; older rows are pruned by
the cron itself so the table stays small).
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel


class OrderSnapshot(SQLModel, table=True):
    """Latest result of the order-polling cron for one store.

    Status values:
      * ``ok``     — poll succeeded with >= 1 order in the queue
      * ``empty``  — poll succeeded with 0 orders (the "đã chạy get
                     lại đơn nhưng chưa tìm thấy đơn" banner copy)
      * ``error``  — poll threw / returned non-2xx
      * ``never``  — the cron has never run for this store (sentinel)
    """

    __tablename__ = "order_snapshots"

    id: int | None = Field(default=None, primary_key=True)
    store_id: int = Field(foreign_key="stores.id", unique=True, index=True)
    merchant_id: str = Field(index=True)
    last_polled_at: datetime | None = Field(default=None)
    next_poll_at: datetime | None = Field(default=None)
    last_order_count: int = Field(default=0)
    last_status: str = Field(default="never")
    message: str = Field(default="")
    updated_at: datetime = Field(default_factory=datetime.utcnow)