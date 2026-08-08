"""Async HTTP client wrapper for the Grab Merchant API.

This is a thin layer over `httpx.AsyncClient` that:

* Centralizes the device fingerprint headers that every request must carry.
* Surfaces an async context-manager interface (`async with GrabClient(...)`).
* Exposes a single `_request()` helper used by every endpoint module so
  we never construct a URL by hand in the endpoint layer.
* Treats `verify_ssl=False` as the default (the existing scripts run with
  MITM proxies — see plan risk R2). Override via the `verify_ssl` kwarg or
  the `GRAB_VERIFY_SSL` env var when running production-style traffic.

Notes:
* The pre-login and post-login flows use slightly different header sets.
  `GrabClient` is intended for the *post-login* flow. The login flow in
  `auth.py` constructs its own `httpx.AsyncClient` for the brief moment
  before `authn_token` exists.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

log = logging.getLogger("pulseorder.grab_client")

# ---------------------------------------------------------------------------
# Device fingerprint — pulled from the captured traffic logs. Every Grab
# Merchant app request must carry these.
# ---------------------------------------------------------------------------
DEVICE_UDID = "da7ca3ef14e2efb04362157a3b8fbbd12be5e387addfab651d5dd0057a9ca2df"
TRACKING_ID = "J7mpkanH6rFmVhCe39zxpM7wm4ahy6iN"
USER_AGENT = "Grab Merchant/4.181.0 (android 12; Build 290)"

BASE_URL = "https://api.grab.com"

# ---------------------------------------------------------------------------
# Static headers every authenticated request must carry. Per-store
# `x-mex-resource` is added per-instance because it varies by store.
# ---------------------------------------------------------------------------
_DEFAULT_HEADERS: dict[str, str] = {
    "host": "api.grab.com",
    "accept": "application/json",
    "x-timezone": "Asia/Bangkok",
    "x-accept-language": "vi-VN;q=1.0",
    "x-deviceudid": DEVICE_UDID,
    "x-tracking-id": TRACKING_ID,
    "user-agent": USER_AGENT,
    "x-device-id": DEVICE_UDID,
    "device-os": "Android",
    "accept-language": "vi_VN",
    "x-grabkit-clientid": "GrabMerchant-App",
    "x-currency": "VND",
    "x-mex-version": "v2",
    "x-agent": "mexapp",
    "x-grab-id-audience": "FOODMAX",
    "x-client-id": "grabfood",
    "mex-country": "VN",
    "mex-type": "MEXUSERS",
    "x-platform-type": "android",
    "business-type": "FOOD",
    "device-model": "SM-F731B",
    "accept-encoding": "gzip",
    "networkkit-disable-gzip": "true",
    "content-type": "application/json; charset=utf-8",
}


class GrabClient:
    """Async client for the Grab Merchant API.

    Usage::

        async with GrabClient(
            authn_token=token,
            merchant_id="zeus_store:5-C6VKAT5GRK3CTT",
        ) as client:
            menu = await client.get("/food/merchant/v2/menu", params={"orderID": "", "oosItemID": ""})
    """

    def __init__(
        self,
        authn_token: str,
        merchant_id: str | None = None,
        *,
        verify_ssl: bool | None = None,
        timeout: float = 30.0,
    ) -> None:
        if not authn_token:
            raise ValueError("authn_token is required")
        # merchant_id is optional: user-level endpoints (store-list,
        # user-profile/v2/details) work without the x-mex-resource header.
        # Per-store endpoints (menu, categories, items, modifiers, …) will
        # still require it and the caller must pass it.

        self._authn_token = authn_token
        self._merchant_id = merchant_id

        # SSL verify: env var > explicit kwarg > False default (MITM-friendly)
        if verify_ssl is None:
            verify_ssl = os.environ.get("GRAB_VERIFY_SSL", "").lower() in ("1", "true", "yes")
        self._verify_ssl = verify_ssl
        self._timeout = timeout

        # Lazily created — only when the context manager is entered. We
        # hold the constructor args and build the client in __aenter__
        # so the user's `async with` lifecycle owns the underlying socket.
        self._client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # Async context-manager protocol
    # ------------------------------------------------------------------
    async def __aenter__(self) -> "GrabClient":
        log.debug("GrabClient.__aenter__ called for merchant=%s", self._merchant_id)
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers=self._headers(),
            verify=self._verify_ssl,
            timeout=self._timeout,
        )
        log.debug("GrabClient httpx.AsyncClient created for merchant=%s", self._merchant_id)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        log.debug("GrabClient.__aexit__ called for merchant=%s", self._merchant_id)
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Header construction
    # ------------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        """Return the request header dict for the current instance.

        Note: we rebuild per-instance so that the auth token + merchant id
        stay mutable. The dict is shallow-copied so the static template is
        never mutated by callers.  `x-mex-resource` is only emitted when
        we actually have a merchant_id — user-level endpoints (store-list
        etc.) work fine without it.
        """
        headers = dict(_DEFAULT_HEADERS)
        headers["authorization"] = self._authn_token
        headers["x-mts-ssid"] = self._authn_token
        if self._merchant_id:
            headers["x-mex-resource"] = self._merchant_id
        return headers

    # ------------------------------------------------------------------
    # Generic request dispatcher
    # ------------------------------------------------------------------
    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Run a single request through the underlying httpx client.

        Raises:
            RuntimeError: if called outside an `async with` block.
            httpx.HTTPError: on transport-level failure.
        """
        if self._client is None:
            # Log detailed info to help debug
            import traceback
            log.error(
                "GrabClient._request called with _client=None. merchant=%s. Trace:\n%s",
                self._merchant_id,
                "".join(traceback.format_stack()),
            )
            raise RuntimeError(
                f"GrabClient must be used inside `async with GrabClient(...) as c`. "
                f"merchant={self._merchant_id}"
            )
        merge_headers = headers or {}
        return await self._client.request(
            method,
            path,
            params=params,
            json=json,
            headers=merge_headers or None,
        )

    # ------------------------------------------------------------------
    # Convenience verbs — every endpoint module calls these.
    # ------------------------------------------------------------------
    async def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        # `headers` mirrors `post`. Some GETs need an extra header the
        # shared set doesn't carry — the marketing campaigns endpoint
        # wants `x-marketing-version`, and without it Grab answers with a
        # different (older) payload shape.
        return await self._request("GET", path, params=params, headers=headers)

    async def post(
        self,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        return await self._request("POST", path, params=params, json=json, headers=headers)

    async def put(
        self,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        return await self._request("PUT", path, params=params, json=json)

    async def delete(
        self,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        return await self._request("DELETE", path, params=params, json=json)

    # ------------------------------------------------------------------
    # Helpers used by some endpoints
    # ------------------------------------------------------------------
    @property
    def merchant_id(self) -> str | None:
        return self._merchant_id

    @property
    def authn_token(self) -> str:
        return self._authn_token
