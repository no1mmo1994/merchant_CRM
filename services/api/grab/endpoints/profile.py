"""User profile + unified profile endpoints."""

from grab.client import GrabClient


async def get_user_profile(client: GrabClient) -> dict:
    """GET /mex-app/troy/user-profile/v2/details — bare user profile."""
    res = await client.get("/mex-app/troy/user-profile/v2/details")
    res.raise_for_status()
    return res.json()


async def get_unified_profile(client: GrabClient) -> dict:
    """GET /mex-app/troy/user-profile/v1/unified-profile — full store + bank info.

    Accepts an optional `isBalanceNeeded` query flag (default false).
    """
    res = await client.get(
        "/mex-app/troy/user-profile/v1/unified-profile",
        params={"isBalanceNeeded": "false"},
    )
    res.raise_for_status()
    return res.json()


async def get_store_list(client: GrabClient) -> dict:
    """GET /mex-app/troy/user-profile/v1/store-list — list of merchant stores.

    Returns the full JSON envelope; the `data.stores` key holds the list.
    """
    res = await client.get("/mex-app/troy/user-profile/v1/store-list")
    res.raise_for_status()
    return res.json()


async def get_merchant(client: GrabClient) -> dict:
    """GET /food/merchant/v2/merchants — current merchant + opening hours.

    Mirrors ``cuahang/trangthai.py`` which hits the same endpoint via
    ``requests.get()`` with the merchant app's headers. The response
    envelope is::

        {
          "merchant": {
            "name":         "Quán Test",
            "isOpen":       true,
            "openingHours": [
              {"ranges": [{"start": "08:00", "end": "22:00"}]},  # Mon
              ...
              6 more days
            ],
            ...
          },
          ...
        }

    The dashboard's overview card uses this to show two pieces of
    state the unified-profile endpoint does not surface:

    * ``isOpen``         — live boolean (closed right now or open).
    * ``openingHours``   — 7-day operating-hours table the operator
                           can read at a glance without opening the
                           Grab merchant app.

    Note: ``/v2/merchants`` and ``/v1/business-attributes`` are
    separate endpoints with different auth claims; we keep this as
    its own helper so failure isolation works the same as the rest.
    """
    res = await client.get("/food/merchant/v2/merchants")
    res.raise_for_status()
    return res.json()


async def get_open_status_v3(client: GrabClient) -> dict:
    """GET /food/merchant/v3/open-status — realtime store runtime state.

    Mirrors ``cuahang/trangthai2.py``. Unlike ``v2/merchants`` which
    returns a single ``isOpen`` boolean, ``v3/open-status`` distinguishes
    THREE runtime states via ``statusDisplayInfo.statusLabel``::

        "Open"      — store is NORMAL (accepting orders normally)
        "BusyMode"  — store is BUSY   (accepting orders with longer
                                     prep times, e.g. "Bận 15 phút")
        "Paused"    — store is TEMPPAUSED (not accepting orders,
                                     e.g. "Nghỉ hôm nay")

    Plus a human-readable ``statusContent`` string the Grab merchant
    app shows on the home screen (e.g. "Quán đang bận", "Đang mở cửa",
    "Đang tạm nghỉ, mở lại lúc 21:00").

    Why we use this rather than the boolean ``isOpen``:
      The boolean conflates "BUSY" with "OPEN" — both return ``true``.
      The dashboard cannot show a "Bận 15 phút" badge from a boolean
      alone; it needs the ``statusLabel`` enum. Per the merchant
      app's contract, ``isOpen = (statusLabel ∈ {Open, BusyMode})``
      — only ``Paused`` flips ``isOpen`` to false. The projection
      step in the router maps both ``Open`` and ``BusyMode`` to
      ``is_open=true`` to preserve that semantic.
    """
    res = await client.get("/food/merchant/v3/open-status")
    res.raise_for_status()
    return res.json()
