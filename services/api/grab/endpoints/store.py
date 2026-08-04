"""Store metadata + state-mutation endpoints (business attributes, scorecard, status).

The status-update helpers in this module are the dashboard's mirror of the
two merchant scripts:

* ``cuahang/setting_timecuahang.py`` — temporary pause (``TEMPPAUSED``)
  with ``tempPauseEnd`` so the store auto-resumes. Used for "Nghỉ 1 tiếng",
  "Nghỉ 2 tiếng", "Nghỉ hôm nay", "Nghỉ 30 ngày" and the inverse "Mở lại".
* ``cuahang/sêtting_busy.py`` — busy mode (``BUSY``) with a
  ``busyModeFoodPrepareTime`` (15 / 30 / 60 minutes) so the customer app
  shows the longer prep time. Also supports "Mở cửa bình thường".
* ``cuahang/trangthai2.py`` — combined script that calls
  ``GET /food/merchant/v3/open-status`` *first*, then sends the PUT with
  the actual `fromState`. We mirror that pattern in
  :func:`fetch_current_runtime_state_label` so the helpers below can
  derive `fromState` server-side and never trust a possibly-stale
  client-side value.

Both endpoints hit ``PUT /food/merchant/v1/merchant/status`` with the
smallest payload the merchant app uses. We accept a richer input here
and fold it onto the wire format.
"""

from __future__ import annotations

from datetime import datetime, timezone

from grab.client import GrabClient


# ---------------------------------------------------------------------------
# Read endpoints (existing)
# ---------------------------------------------------------------------------
async def get_business_attributes(client: GrabClient, merchant_id: str | None = None) -> dict:
    """GET /food/merchant/v1/business-attributes — merchant verification data.

    The merchant_id is required by Grab as a query parameter; if not
    supplied, we use the client's bound merchant_id stripped of the
    `zeus_store:` prefix.
    """
    mid = merchant_id or client.merchant_id.removeprefix("zeus_store:")
    res = await client.get(
        "/food/merchant/v1/business-attributes",
        params={"merchantID": mid},
    )
    res.raise_for_status()
    return res.json()


async def get_scorecard(client: GrabClient) -> dict:
    """GET /mex-app/troy/scorecard/v1/profile — store rating + tier."""
    res = await client.get(
        "/mex-app/troy/scorecard/v1/profile",
        params={"screen": "ENTRY"},
    )
    res.raise_for_status()
    return res.json()


# ---------------------------------------------------------------------------
# Status write endpoints — mirror cuahang/setting_*.py scripts
# ---------------------------------------------------------------------------
async def set_store_temp_paused(
    client: GrabClient,
    *,
    pause_end_utc: datetime | None = None,
    is_unpause: bool = False,
    current_runtime: str | None = None,
) -> dict:
    """Toggle the store's ``TEMPPAUSED`` state.

    Mirrors ``cuahang/setting_timecuahang.py``. The merchant app sends:

        PUT /food/merchant/v1/merchant/status
        {
          "fromState": "NORMAL",
          "toState":   "TEMPPAUSED",
          "busyModeRequest":  {},
          "tempPauseRequest": {
            "isUnpause":    false,
            "tempPauseEnd": "2026-08-03T11:00:00.000000Z"  // ISO-8601 UTC µs
          }
        }

    For unpause (``Mở lại hoạt động bình thường``):

        {
          "fromState": "TEMPPAUSED",
          "toState":   "NORMAL",
          "busyModeRequest":  {},
          "tempPauseRequest": { "isUnpause": true }
        }

    ``pause_end_utc`` is ignored when ``is_unpause`` is True.

    `current_runtime` resolution — defence in depth, mirrors
    `cuahang/trangthai2.py`:

      1. If the dashboard supplied a value, trust it (cheap fast path).
      2. Otherwise, fetch `v3/open-status` *right now* and use what
         Grab actually has on its side. This is the canonical fix for
         the operator-reported 409 errors — the dashboard's
         `useStoreOpeningHours` cache can be up to 30 s stale and
         `tempPauseEnd` auto-resumes run on Grab's clock, not ours.
      3. If both the client value and the live fetch are unusable,
         fall back to `"NORMAL"` — same behaviour as the very first
         version of this helper. We never want to 5xx our own caller
         just because Grab blipped.
    """
    from_state = await _resolve_runtime(
        client,
        current_runtime,
        default="NORMAL",
    )
    if is_unpause:
        to_state = "NORMAL"
        temp_pause_request: dict = {"isUnpause": True}
    else:
        if pause_end_utc is None:
            raise ValueError("pause_end_utc is required when is_unpause is False")
        # Strip tzinfo to match what the merchant app sends — ISO with 'Z'.
        if pause_end_utc.tzinfo is not None:
            pause_end_utc = pause_end_utc.astimezone(timezone.utc).replace(tzinfo=None)
        to_state = "TEMPPAUSED"
        # `%f` → 6-digit microseconds — exactly mirrors
        # `cuahang/setting_timecuahang.py`:
        #     end_time_utc.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        # The merchant app parses the trailing digits as µs, so sending
        # only 3 (ms) silently fails to match the merchant app's payload
        # and Grab rejects it on auto-resume. Keep them aligned.
        temp_pause_request = {
            "isUnpause": False,
            "tempPauseEnd": pause_end_utc.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z",
        }

    payload = {
        "fromState": from_state,
        "toState": to_state,
        "busyModeRequest": {},
        "tempPauseRequest": temp_pause_request,
    }
    res = await client.put("/food/merchant/v1/merchant/status", json=payload)
    res.raise_for_status()
    return res.json()


async def set_store_busy(
    client: GrabClient,
    *,
    busy_minutes: int | None = None,
    is_unpause: bool = False,
    current_runtime: str | None = None,
) -> dict:
    """Toggle the store's ``BUSY`` state.

    Mirrors ``cuahang/sêtting_busy.py``. The merchant app sends:

        PUT /food/merchant/v1/merchant/status
        {
          "fromState": "NORMAL",
          "toState":   "BUSY",
          "busyModeRequest":  {
            "busyModeFoodPrepareTime": 15,   // minutes — 15 / 30 / 60
            "option": 0
          },
          "tempPauseRequest": {}
        }

    For unbusy ("Mở cửa hoạt động bình thường" — exits BUSY or TEMPPAUSED):

        {
          "fromState": "BUSY",
          "toState":   "NORMAL",
          "busyModeRequest":  {},
          "tempPauseRequest": { "isUnpause": true }
        }

    ``busy_minutes`` must be one of 15 / 30 / 60.

    `current_runtime` resolution is identical to
    `set_store_temp_paused` — client fast path → live
    `v3/open-status` fetch → `"NORMAL"` fallback.
    """
    from_state = await _resolve_runtime(
        client,
        current_runtime,
        default="NORMAL",
    )
    if is_unpause:
        to_state = "NORMAL"
        busy_request: dict = {}
        temp_pause_request: dict = {"isUnpause": True}
    else:
        if busy_minutes not in (15, 30, 60):
            raise ValueError("busy_minutes must be one of 15, 30, 60")
        to_state = "BUSY"
        busy_request = {
            "busyModeFoodPrepareTime": busy_minutes,
            "option": 0,
        }
        temp_pause_request = {}

    payload = {
        "fromState": from_state,
        "toState": to_state,
        "busyModeRequest": busy_request,
        "tempPauseRequest": temp_pause_request,
    }
    res = await client.put("/food/merchant/v1/merchant/status", json=payload)
    res.raise_for_status()
    return res.json()


async def _resolve_runtime(
    client: GrabClient,
    current_runtime: str | None,
    *,
    default: str,
) -> str:
    """Pick the `fromState` to put on the wire.

    * Use the dashboard-supplied value if it parses cleanly.
    * Otherwise hit `v3/open-status` so we never send a stale state.
    * Fall back to ``default`` only when both are unusable.
    """
    if current_runtime in ("Open", "BusyMode", "Paused"):
        return _resolve_from_state(current_runtime, default=default)
    live = await fetch_current_runtime_state_label(client)
    if live is not None:
        return live
    return default


# ---------------------------------------------------------------------------
# Internal — translate `v3/open-status` runtime into the `fromState`
# Grab wants in the `PUT /food/merchant/v1/merchant/status` body.
# ---------------------------------------------------------------------------
async def fetch_current_runtime_state_label(client: GrabClient) -> str | None:
    """Authoritative runtime state straight from Grab.

    Returns one of ``"NORMAL"``, ``"BUSY"``, ``"TEMPPAUSED"`` — the
    canonical names Grab's `PUT /food/merchant/v1/merchant/status`
    accepts as `fromState`. Returns ``None`` when the upstream call
    fails or returns an unexpected `statusLabel`.

    Why server-side: the operator reported a class of 409 Conflict
    errors caused by the dashboard sending a `fromState` that didn't
    match Grab's actual store state — usually because the operator's
    last poll was stale, Grab auto-resumed a temp pause, or the dialog
    was opened in a window where the React Query cache hadn't refreshed.
    Mirrors ``cuahang/trangthai2.py``: that script also hits
    `v3/open-status` immediately before sending the PUT.

    We deliberately do NOT log here: helpers below already log
    surrounding context. A duplicated log line just drowns the output.
    """
    res = await client.get("/food/merchant/v3/open-status")
    if res.status_code != 200:
        return None
    try:
        label = res.json().get("statusDisplayInfo", {}).get("statusLabel")
    except (ValueError, AttributeError):
        return None
    return _runtime_state_label_to_from_state(label)


def _runtime_state_label_to_from_state(label: str | None) -> str | None:
    """Map the dashboard's three-state enum onto Grab's `fromState`.

    Returns ``None`` for unknown / missing labels so callers can fall
    back to a safe default rather than sending garbage to Grab.

    Note the difference in spelling: Grab uses uppercase enum names
    ("NORMAL", "BUSY", "TEMPPAUSED") in the PUT body, while the
    dashboard uses mixed-case enum names ("Open", "BusyMode",
    "Paused") in the v3/open-status response. Keep both mappings here.
    """
    if label == "Open":
        return "NORMAL"
    if label == "BusyMode":
        return "BUSY"
    if label == "Paused":
        return "TEMPPAUSED"
    return None


def _resolve_from_state(current_runtime: str | None, *, default: str) -> str:
    """Map the canonical dashboard runtime state onto Grab's `fromState`.

    * ``"Open"``     → ``"NORMAL"``
    * ``"BusyMode"`` → ``"BUSY"``
    * ``"Paused"``   → ``"TEMPPAUSED"``
    * unknown / missing → ``default`` (callers pass ``"NORMAL"``).

    Why a helper instead of an inline dict: every state change on the
    backend needs this mapping, and forgetting one branch would 409 the
    request the first time the store ends up in that state. Keep the
    logic in one place so both ``set_store_temp_paused`` and
    ``set_store_busy`` agree on it.
    """
    if current_runtime == "BusyMode":
        return "BUSY"
    if current_runtime == "Paused":
        return "TEMPPAUSED"
    if current_runtime == "Open":
        return "NORMAL"
    return default
