"""Grab merchant passcode (PIN) validation — the gate on menu writes.

Captured from the Merchant app on 2026-08-08 in the request set the
operator supplied:

    POST /food/merchant/passcode/validate
    {"passcode": "<32-hex app-computed hash>"}

The endpoint path and body shape are proven. Two things about it are
**not**, and both block turning this into a dashboard feature:

1. `passcode` is a client-computed 32-hex hash, not the PIN itself. It is
   not a plain hash of the digits: an exhaustive search of every 4-to-8
   digit PIN under MD5, SHA-256[:32], and the obvious device / session /
   store / account salts did not reproduce the captured value. So the
   Grab Merchant app folds in a secret (an app pepper, or a server
   challenge fetched just before) that this web dashboard does not have
   and cannot derive from a capture of the PIN screen alone.

2. The only captured attempt answered **409** — a rejected passcode — and
   the app then went to its "Forgot PIN" flow. There is no captured
   success, so the success status and response are unknown too.

Because of (1), the dashboard cannot compute the hash Grab expects.
Because of (2) plus the app's own `failureCountThreshold: 3`, feeding a
*guessed* hash would spend the operator's attempts and could lock their
merchant PIN. So this function exists as a proven, verified building
block, but nothing feeds it a PIN — it stays dormant until a capture of a
**successful** validate (with the plaintext PIN, or the request right
before it that carries a challenge) makes the hash reproducible.

Never call this with a hash derived from a guessed algorithm.
"""

from __future__ import annotations

import logging

import httpx

from grab.client import GrabClient

log = logging.getLogger("pulseorder.grab.passcode")

VALIDATE_PATH = "/food/merchant/passcode/validate"


async def validate_passcode(client: GrabClient, passcode_hash: str) -> bool:
    """POST the app-computed passcode hash. True when Grab accepts it.

    `passcode_hash` must be the value the Merchant app would send — the
    32-hex digest, **not** the raw PIN. See the module docstring for why
    the dashboard cannot compute that yet.

    Returns False for the rejection codes (the captured 409, plus the
    400/401/403 a wrong or missing passcode would plausibly draw) rather
    than raising, so a caller can tell "wrong PIN" from "Grab is down".
    Anything else — a 5xx, a transport error — propagates, because that is
    not the operator's PIN being wrong.
    """
    res = await client.post(VALIDATE_PATH, json={"passcode": passcode_hash})
    if res.status_code < 300:
        return True
    if res.status_code in (400, 401, 403, 409):
        log.info("passcode validate rejected: %s", res.status_code)
        return False
    res.raise_for_status()
    return False  # unreachable when raise_for_status fires, but explicit
