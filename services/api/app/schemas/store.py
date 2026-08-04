"""Pydantic schemas for store endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Store runtime status (v3/open-status)
# ---------------------------------------------------------------------------
# The Grab merchant app displays three runtime states on the home screen:
#
#   "Open"      — NORMAL (accepting orders normally)
#   "BusyMode"  — BUSY   (accepting orders with longer prep times)
#   "Paused"    — TEMPPAUSED (not accepting orders)
#
# `trangthai2.py` mirrors this on the wire via
# `GET /food/merchant/v3/open-status` → `statusDisplayInfo.statusLabel`.
# We expose it as a `Literal` so the OpenAPI schema enumerates the
# exact values and the frontend gets autocomplete on the three cases.
StoreRuntimeStatus = Literal["Open", "BusyMode", "Paused"]


class StoreOut(BaseModel):
    id: int
    merchant_id: str
    name: str
    address: str
    last_refresh_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class StoreListResponse(BaseModel):
    stores: list[StoreOut]


class SelectStoreRequest(BaseModel):
    merchant_id: str


# ---------------------------------------------------------------------------
# Store-status update request
# ---------------------------------------------------------------------------
# Two distinct surfaces hit Grab's `PUT /food/merchant/v1/merchant/status`:
#   * `temp_pause`  — NORMAL ↔ TEMPPAUSED (Nghỉ 1h/2h/hôm nay/30 ngày,
#                     Mở lại). Required `pause_end_utc` unless `unpause`.
#   * `busy`        — NORMAL ↔ BUSY (Bận 15/30/60 phút, Mở lại bình
#                     thường). Required `minutes` unless `unpause`.
#
# The frontend sends a `kind` discriminator so the router can fold both
# onto a single endpoint and forward to the right helper. We intentionally
# keep `kind` as a `Literal` (instead of free-form string) so OpenAPI
# surfaces the exact enum and we get 422 on bad values.
StoreStatusKind = Literal["temp_pause", "busy"]


class UpdateStoreStatusRequest(BaseModel):
    """Payload for POST /api/stores/{merchant_id}/status.

    Exactly one operation is dispatched per request — the router reads
    `kind` to pick which Grab endpoint helper to call:

    * ``kind="temp_pause"`` → ``set_store_temp_paused()``
        - ``unpause=True`` exits TEMPPAUSED → NORMAL.
        - Otherwise ``pause_end_utc`` is required (auto-resume time).
    * ``kind="busy"`` → ``set_store_busy()``
        - ``unpause=True`` exits BUSY → NORMAL.
        - Otherwise ``minutes`` must be 15 / 30 / 60.

    `pause_end_utc` is in UTC (matches what the merchant app sends). The
    frontend should compute it client-side in the user's timezone.

    `current_runtime` is the **server-of-truth for the
    `fromState` field** Grab's `PUT /food/merchant/v1/merchant/status`
    expects in the body. The frontend reads it from
    `GET /food/merchant/v3/open-status` (same source as
    `cuahang/trangthai2.py`) and passes it here so we don't have to
    take a second round-trip from the backend. The router validates
    the value against the enum and falls back to `"NORMAL"` if the
    frontend omits it (preserving the previous behaviour for any
    external API consumers).
    """

    kind: StoreStatusKind
    unpause: bool = False
    pause_end_utc: datetime | None = None
    minutes: Literal[15, 30, 60] | None = None
    current_runtime: StoreRuntimeStatus | None = None


class UpdateStoreStatusResponse(BaseModel):
    """Outcome of a status change.

    `raw` carries the verbatim Grab response (so callers can introspect
    `isFirstStepSuccess` / `isSecondStepSuccess`).
    """

    merchant_id: str
    kind: StoreStatusKind
    unpause: bool
    raw: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Store opening-hours (read-only) — mirrors cuahang/trangthai.py
# ---------------------------------------------------------------------------
# Grab's `GET /food/merchant/v2/merchants` returns the live merchant
# state the merchant app displays on its home screen. Two fields are
# interesting for the dashboard's overview card and they are not
# surfaced by `unified-profile`:
#
#   * `merchant.isOpen`        — live boolean (open right now).
#   * `merchant.openingHours`  — 7-day array (Mon..Sun), each entry
#                                is `{ranges: [{start, end}]}`.
#
# We project these into a small response schema so the frontend does
# not need to know the raw Grab envelope. `raw` carries the verbatim
# payload for debugging / future field use.


class OpeningHourRange(BaseModel):
    """One opening-hour window. `start` / `end` are local-time strings
    in Grab's `HH:MM` 24-hour format. Empty `start` means "closed all day"."""

    start: str = ""
    end: str = ""


class OpeningHourDay(BaseModel):
    """A single day's schedule. `ranges` is a list because some stores
    split opening hours into AM / PM sessions (e.g. 08:00–14:00, 17:00–22:00)."""

    day_index: int  # 0..6 — matches Grab's array order (0 = Monday)
    ranges: list[OpeningHourRange] = Field(default_factory=list)


class OpeningHoursData(BaseModel):
    """Realtime merchant state for the overview card.

    Three sources are merged into this payload by the router:

    * `name` + `opening_hours[]`     — from `GET /food/merchant/v2/merchants`
                                       (matches `cuahang/trangthai.py`).
    * `status_label` + `status_content` + `is_open`
                                    — from `GET /food/merchant/v3/open-status`
                                       (matches `cuahang/trangthai2.py`).
    * `status_note`                 — operator-friendly sentence the
                                       dashboard renders under the pill
                                       so the merchant knows what state
                                       the store is currently in and
                                       when it resumes.

    `status_label` is the canonical enum:
      "Open"     → store NORMAL → green pill
      "BusyMode" → store BUSY   → amber pill (is_open still true)
      "Paused"   → store TEMPPAUSED → red pill (is_open = false)
    `is_open` is preserved for backwards-compat with code that only
    cares whether the store is accepting orders (BUSY = still open).
    """

    name: str | None = None
    is_open: bool | None = None
    status_label: StoreRuntimeStatus | None = None
    status_content: str | None = None
    status_note: str | None = None
    opening_hours: list[OpeningHourDay] = Field(default_factory=list)


class OpeningHoursResponse(BaseModel):
    """`GET /api/stores/{merchant_id}/opening-hours` payload.

    Wraps the projected Grab data in `{ok, data, error}` like the
    rest of the stores router so a flaky Grab response doesn't take
    down the whole overview card — `error` is non-null and `data`
    is empty when the upstream call fails.
    """

    ok: bool
    data: OpeningHoursData = Field(default_factory=OpeningHoursData)
    error: str | None = None
