"""Order retrieval endpoints — mirror of the ``donhang/`` scripts.

The merchant scripts (`donhang/getdonhangmoi.py` +
`donhang/donhanghoantat_dondalamxong.py`) hit five endpoints:

  * ``GET /food/merchant/v3/orders-pagination?pageType=Preparing`` —
    returns the prep-queue summary (displayID, eater, items count,
    state, times).
  * ``GET /food/merchant/v3/orders/{order_id}?deviceTimeInMillis=…`` —
    returns full order detail (items + modifiers + fare + eater
    address/phone/comment + mexOPT delay flag).
  * ``GET /food/merchant/v1/scheduled-orders`` — the "sắp tới" bucket
    (orders scheduled for a later pickup window).
  * ``GET /food/merchant/v1/reports/daily-pagination?states=COMPLETED`` —
    the "đã hoàn tất" bucket for a date range.
  * ``GET /food/merchant/v1/reports/daily-pagination?states=CANCELLED`` —
    the "đã hủy" bucket for a date range.

We expose all five here so the dashboard can render the same data
without the operator copy/pasting tokens into a Python REPL.

The `Preparing` pageType is the only one the live merchant currently
sees data on for the pagination endpoint — ``All/New/Ready/Completed``
have returned 0 rows in our tests, so completed/cancelled history
comes from the ``reports/daily-pagination`` endpoint instead.
"""

from __future__ import annotations

import time
from typing import Any

from grab.client import GrabClient


async def list_preparing_orders(
    client: GrabClient,
    *,
    auto_accept_group: str = "1",
) -> dict[str, Any]:
    """Fetch the merchant's preparing-order queue.

    Mirrors ``donhang/getdonhangmoi.py:get_preparing_orders`` exactly:
    ``GET /food/merchant/v3/orders-pagination?pageType=Preparing`` with
    `autoAcceptGroup` (the merchant dashboard toggle) and an empty
    `timestamp` (lets Grab paginate from the latest snapshot).

    Returns the raw ``{"orders": [...], ...}`` envelope. The router
    projects each row into a stable summary shape.
    """
    res = await client.get(
        "/food/merchant/v3/orders-pagination",
        params={
            "pageType": "Preparing",
            "autoAcceptGroup": auto_accept_group,
            "timestamp": "",
        },
    )
    res.raise_for_status()
    return res.json()


async def get_order_detail(
    client: GrabClient,
    order_id: str,
) -> dict[str, Any]:
    """Fetch full order detail by ID.

    Mirrors ``donhang/getdonhangmoi.py:get_order_details``. The
    `deviceTimeInMillis` query param is required (otherwise Grab rejects
    with 4xx) — the script always passes the current epoch ms.

    Returns the raw ``{"order": {...}}`` envelope. The router flattens
    it into nested Pydantic models (eater, items, modifiers, fare,
    times, mexOPT).
    """
    if not order_id:
        raise ValueError("order_id is required")

    device_time = int(time.time() * 1000)
    res = await client.get(
        f"/food/merchant/v3/orders/{order_id}",
        params={"deviceTimeInMillis": device_time},
    )
    res.raise_for_status()
    return res.json()


async def list_scheduled_orders(client: GrabClient) -> dict[str, Any]:
    """Fetch the merchant's scheduled-order queue.

    Mirrors ``donhang/donhanghoantat_dondalamxong.py:get_scheduled_orders``.
    Wire shape: ``{"orders": [...]}`` — each row carries its own
    ``displayID`` / ``orderID`` so the dashboard can render the
    "Sắp tới" tab without a follow-up detail call.

    The endpoint accepts no parameters (the script makes the same
    call unconditionally); the date filter is implicit (Grab returns
    the upcoming booking window).
    """
    res = await client.get("/food/merchant/v1/scheduled-orders")
    res.raise_for_status()
    return res.json()


async def list_daily_reports(
    client: GrabClient,
    *,
    start_time: str,
    end_time: str,
    state: str,
    page_index: int = 0,
    page_size: int = 100,
) -> dict[str, Any]:
    """Fetch the daily report rows for a state + date range.

    Mirrors ``donhang/donhanghoantat_dondalamxong.py:get_daily_reports``.
    `state` is one of ``COMPLETED`` / ``CANCELLED`` (the only two the
    script requests). The wire shape is ``{"statements": [...]}``;
    each row is a thin summary (displayID, priceDisplay, updatedAt /
    cancelledAt, cancelRole).
    """
    res = await client.get(
        "/food/merchant/v1/reports/daily-pagination",
        params={
            "pageIndex": page_index,
            "pageSize": page_size,
            "startTime": start_time,
            "endTime": end_time,
            "states": state,
        },
    )
    res.raise_for_status()
    return res.json()
