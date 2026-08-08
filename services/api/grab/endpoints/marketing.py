"""Grab marketing: available programs and the campaigns a store joined.

Two unrelated Grab services, captured in `marketing/`:

* `gms/v1/spotlight/events` — the catalogue a store *can* join
  (`marketing/getds_marketinghienco.py`)
* `unifieddemandgen/v1/campaigns` — what it *has* joined, with spend and
  return (`marketing/getds_marketingdangthamgia.py`)

They share nothing: different paths, different response shapes, and the
campaigns one needs an extra header. Kept as two functions rather than
one "marketing" call for that reason.
"""

from __future__ import annotations

import logging
from typing import Any

from grab.client import GrabClient

log = logging.getLogger("pulseorder.grab.marketing")

#: The campaigns endpoint is versioned by header, not by path. Sending
#: the request without it returns an older payload shape that has no
#: `performance` block, so the dashboard would show every campaign with
#: blank spend and ROMS.
_MARKETING_VERSION = {"x-marketing-version": "GrabMerchant Marketing 2.0"}

#: Grab renders the program terms in whatever `accept-language` asks for,
#: and it is fussy about the form. Verified against the live store:
#:
#:   vi     → "Giảm 12.000₫ cho đơn hàng"   ✅
#:   vi-VN  → "12.000₫ off order"            ❌
#:   vi_VN  → "12.000₫ off order"            ❌  (the client default)
#:
#: Only the bare tag works; both regional forms fall back to English. Every
#: capture script under `marketing/` sends `vi`, so this matches the real
#: app. Set per-request rather than on the client because changing the
#: global default would silently reword every other Grab surface too.
_VIETNAMESE = {"accept-language": "vi"}


async def list_spotlight_events(client: GrabClient) -> list[dict[str, Any]]:
    """GET /mex-app/troy/gms/v1/spotlight/events — programs on offer.

    Returns the raw `events` array. Each entry carries `eventID`,
    `name`, `description` and `isEligible`.

    ⚠️ It does **not** carry the economics — no discount amount, no Grab
    co-funding share, no minimum order value. Those appear in the app's
    program-detail screen, which has not been captured. Anything that
    needs "Grab funds X%" has to wait for that capture; this endpoint
    alone cannot answer it.
    """
    res = await client.get(
        "/mex-app/troy/gms/v1/spotlight/events", headers=_VIETNAMESE
    )
    res.raise_for_status()
    data = res.json()
    if not isinstance(data, dict):
        return []
    return [e for e in (data.get("events") or []) if isinstance(e, dict)]


async def get_event_detail(client: GrabClient, event_id: str) -> dict[str, Any]:
    """GET /mex-app/troy/gms/v1/events/{id} — one program's full terms.

    Note the path: `gms/v1/events/{id}`, **not** `gms/v1/spotlight/events/
    {id}`. The list and the detail live on sibling paths, not on a common
    prefix — captured in `marketing/getchitiet_dsmarketing.py`.

    This is the only place Grab exposes a program's economics. The list
    endpoint carries name/description/eligibility and nothing else, so
    the discount, minimum order value and co-funding share can only come
    from here — one request per program.

    Shape: `{name, status, eventID, isEligible, sections: [...]}` where
    each section is `{uiType, params}` and **`params` is a JSON string**,
    not an object. It has to be decoded a second time; see
    `parse_event_sections`.
    """
    res = await client.get(
        f"/mex-app/troy/gms/v1/events/{event_id}", headers=_VIETNAMESE
    )
    res.raise_for_status()
    data = res.json()
    return data if isinstance(data, dict) else {}


async def list_campaigns(
    client: GrabClient,
    *,
    offset: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    """GET /mex-app/troy/unifieddemandgen/v1/campaigns — joined campaigns.

    Returns the raw payload: a `totalCount` block plus one list per
    status (`ongoing`, `evergreen`, `upcoming`, `inReview`, `paused`,
    `past`). Each campaign has an `info` block (name, start/end) and a
    `performance` block (marketingSpend, assistedSales, assistedOrders,
    ssmRoms).

    `campaignType` really is the literal string `"null"`, not an omitted
    parameter and not JSON null — that is what the captured request
    sends, and this is not the API to get creative with.
    """
    res = await client.get(
        "/mex-app/troy/unifieddemandgen/v1/campaigns",
        params={"campaignType": "null", "offset": offset, "limit": limit},
        headers={**_MARKETING_VERSION, **_VIETNAMESE},
    )
    res.raise_for_status()
    data = res.json()
    return data if isinstance(data, dict) else {}
