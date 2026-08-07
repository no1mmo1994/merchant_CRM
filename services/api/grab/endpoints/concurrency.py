"""Grab's menu edit lock.

The Merchant app takes a store-wide lock before it touches the menu, and
releases it when the operator leaves the editor. Writes made without it
can come back 409 Conflict — that is the reason the captured script
`donhang/lienkettuychon.py` calls this first and says so in as many
words.
"""

from __future__ import annotations

import logging

import httpx

from grab.client import GrabClient

log = logging.getLogger("pulseorder.grab.concurrency")

_ENTER = "/food/merchant/v1/concurrency-handling/enter"

#: Grab scopes the lock by feature. `mexMenuEdit` / `all` is what the app
#: sends when the operator opens the menu editor — the broadest menu
#: scope, which is what every write in this codebase needs.
_MENU_EDIT = {"feature": "mexMenuEdit", "subFeature": "all"}


async def acquire_menu_edit_lock(client: GrabClient) -> bool:
    """Ask Grab for permission to edit this store's menu.

    Returns True when Grab granted it, False otherwise. **Never raises.**

    Best-effort on purpose. Every menu write in this codebase has worked
    without the lock often enough that failing a write because the lock
    call failed would be a regression, not a safeguard. The captured
    traffic shows the app taking it, and 409s have been observed on menu
    writes, so taking it should reduce them — but the evidence that it is
    *required* is circumstantial, and treating a lock failure as fatal
    would be acting on that guess in the most expensive direction.

    Callers should log the result and carry on either way.
    """
    try:
        res = await client.post(_ENTER, json=_MENU_EDIT)
    except httpx.HTTPError as exc:
        log.warning("menu edit lock: transport error, continuing without it: %r", exc)
        return False
    if res.status_code == 200:
        return True
    log.warning(
        "menu edit lock: Grab answered %s, continuing without it — %s",
        res.status_code, (res.text or "")[:200],
    )
    return False
