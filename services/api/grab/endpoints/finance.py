"""Finance / revenue endpoints — mirror of ``donhang/getdoanhthu.py``.

The merchant script (`donhang/getdoanhthu.py`) hits::

    POST https://api.grab.com/mex/finances/mobile/v4/transactions/summary

with a date-range payload and walks the recursive ``data.uiBreakdown``
tree to pull the Vietnamese-labelled rows. We expose the same call here
so the dashboard can render the same numbers without the operator
copy/pasting tokens into a Python REPL.

Sibling endpoints the merchant app also shows ("Giao dịch" tab +
"Số tiền thu về" tab) live here too:

  * ``POST /mex/finances/mobile/v4/transactions/list`` — transaction
    history (one row per order / ad-spend / settlement).
  * ``POST /mex/finances/mobile/v4/settlements/list`` — payout rows
    ("Đã chuyển khoản" status), matches the "Chi tiết thanh toán"
    list in the merchant mobile app.
  * ``POST /mex/finances/mobile/v4/settlements/summary`` — top totals
    ("Số dư" / "Còn thiếu Grab") that appear above the settlement
    list.

Why a separate module rather than `grab/endpoints/store.py`: finance
lives under ``/mex/finances/...`` (mex-app surface), not
``/food/merchant/...`` — different path, different audience. Keeps the
separation visible so a future maintainer can grep for it.
"""

from __future__ import annotations

from typing import Any

from grab.client import GrabClient


def _date_range_payload(
    start_date: str,
    end_date: str,
    *,
    limit: int,
    business_line: str = "GF",
    currency: str = "VND",
) -> dict[str, Any]:
    """Build the standard ``filters.dateTime`` envelope used by every
    finance endpoint.

    Kept as a single helper so a future Grab change (e.g. adding
    ``timezone`` or splitting the filters) only needs to be applied in
    one place. Mirrors the payload the merchant script sends.
    """
    return {
        "businessLine": business_line,
        "limit": limit,
        "currency": currency,
        "filters": {
            "dateTime": {
                "from": start_date,
                "to": end_date,
                "frequency": "custom",
            }
        },
    }


async def get_financial_summary(
    client: GrabClient,
    *,
    start_date: str,
    end_date: str,
    limit: int = 10,
    business_line: str = "GF",
    currency: str = "VND",
) -> dict[str, Any]:
    """Fetch a financial summary for ``[start_date, end_date]``.

    Mirrors ``donhang/getdoanhthu.py:get_store_financial_summary`` exactly:

      * payload shape::

            {
              "businessLine": "GF",
              "limit": 10,
              "currency": "VND",
              "filters": {"dateTime": {"from": "...", "to": "...",
                                        "frequency": "custom"}}
            }

      * the response envelope is ``{"data": {..., "uiBreakdown": [...],
        "salesBalance": ..., "earningsBalance": ...}}`` — the recursive
        walker in the router projects that into a flat
        ``metrics[label] -> [values]`` map.

    `start_date` / `end_date` are ``YYYY-MM-DD`` strings (the same format
    the merchant script prompts for). Date validation is the caller's
    responsibility — we forward whatever the dashboard sends so a typo
    surfaces as a 4xx from Grab rather than being silently swallowed.

    Returns the raw response body (parsed JSON). The router does the
    uiBreakdown walk so this helper stays dumb.
    """
    payload = _date_range_payload(
        start_date,
        end_date,
        limit=limit,
        business_line=business_line,
        currency=currency,
    )
    res = await client.post(
        "/mex/finances/mobile/v4/transactions/summary",
        json=payload,
    )
    res.raise_for_status()
    return res.json()


async def list_transactions(
    client: GrabClient,
    *,
    start_date: str,
    end_date: str,
    limit: int = 50,
    business_line: str = "GF",
    currency: str = "VND",
) -> dict[str, Any]:
    """Fetch the per-transaction ledger for ``[start_date, end_date]``.

    Powers the "Giao dịch" tab. Returns rows of::

        {
          "id": "...", "name": "...", "amount": <int>,
          "amountDisplay": "...", "datetime": "<ISO>",
          "transactionDate": "<display string>",
          "displayDate": "<day label>", "type": "Food delivery" | "Marketing" | ...,
          "currency": {...}
        }

    Same payload envelope as the summary call (the only thing that
    changes is the path). The router hands each row to the schema
    layer so the dashboard gets a stable TS shape regardless of what
    extra fields Grab decides to add in the future.
    """
    payload = _date_range_payload(
        start_date,
        end_date,
        limit=limit,
        business_line=business_line,
        currency=currency,
    )
    res = await client.post(
        "/mex/finances/mobile/v4/transactions/list",
        json=payload,
    )
    res.raise_for_status()
    return res.json()


async def list_settlements(
    client: GrabClient,
    *,
    start_date: str,
    end_date: str,
    limit: int = 50,
    business_line: str = "GF",
    currency: str = "VND",
) -> dict[str, Any]:
    """Fetch the settlement (payout) history for ``[start_date, end_date]``.

    Powers the "Số tiền thu về" tab's "Chi tiết thanh toán" list.
    Returns rows shaped like::

        {
          "id": "SVNAUTZRMJSH",
          "amount": 606451,
          "datetime": "<ISO>",
          "transactionDate": "04/08/2026 04:55AM",
          "displayDate": "03 08 2026",
          "type": "Transferred",       # Grab's localized "Đã chuyển khoản"
          "currency": {...}
        }

    The router maps ``type`` to a Vietnamese status label and groups
    rows by `displayDate` so the dashboard renders one card per
    payout date, matching the merchant mobile app.
    """
    payload = _date_range_payload(
        start_date,
        end_date,
        limit=limit,
        business_line=business_line,
        currency=currency,
    )
    res = await client.post(
        "/mex/finances/mobile/v4/settlements/list",
        json=payload,
    )
    res.raise_for_status()
    return res.json()


async def get_settlements_summary(
    client: GrabClient,
    *,
    start_date: str,
    end_date: str,
    limit: int = 20,
    business_line: str = "GF",
    currency: str = "VND",
) -> dict[str, Any]:
    """Fetch the top-line settlement balance for ``[start_date, end_date]``.

    Powers the "Số dư" / "Còn thiếu Grab" tiles above the settlement
    list. Response envelope::

        {
          "accountsPayableBalance": 253676,   # amount Grab still owes
          "owedToGrab": 0,                    # amount merchant owes Grab
          "currency": {...},
          "status": "",
          "notifications": null
        }

    The names are unusual (Grab's backend terminology treats Grab as
    the "accounts payable" party for merchants in Vietnam), so the
    router renames them to clearer Vietnamese labels before returning.
    """
    payload = _date_range_payload(
        start_date,
        end_date,
        limit=limit,
        business_line=business_line,
        currency=currency,
    )
    res = await client.post(
        "/mex/finances/mobile/v4/settlements/summary",
        json=payload,
    )
    res.raise_for_status()
    return res.json()
