"""Wire shape for the partner API (``/api/partner/*``).

This is intentionally separate from ``schemas/orders.py`` and
``schemas/customers.py``: the partner API exposes a REDUCED,
PARTNER-FACING shape (only what the user wants to grant a partner
access to) — customer name, phone, items, price, source. We don't
leak Grab's internal fields (state, timestamps, modifier IDs, …)
because the operator asked for the minimum fields they need to
share.

Field reference (per the user's spec, translated):

  * ``customerName``  — from ``eater.name`` in the archive's
                        ``detail_json``.
  * ``phone``         — from ``eater.mobileNumber``. If Grab
                        anonymised the row (name="***" + phone=""),
                        we surface both fields empty rather than
                        the literal "***" / "" so the partner sees
                        consistent empty semantics.
  * ``items``         — list of line-item snapshots from
                        ``itemInfo.items[]``. Each entry has the
                        dish name + qty + locale price. We use
                        ``OrderItemLite`` (a 3-field subset of
                        ``OrderItem``) because the partner doesn't
                        need modifier IDs / IDs / weights.
  * ``price``         — ``fare.totalDisplay`` (locale-formatted
                        VND string like "305.000"). Kept as a
                        string to match what Grab returns — no
                        float round-trip.
  * ``source``        — ``"GF " + Store.region`` per the user's
                        contract: the region is auto-derived from
                        the store's address at write time. If the
                        store has no address yet we fall back to
                        ``"GF "`` (just the prefix) so partners
                        still see a non-empty source.
  * ``orderId`` /
    ``displayId``     — unique + human-readable IDs so partners
                        can deduplicate / quote orders back to the
                        dashboard.
  * ``state``         — the archive's last-seen state
                        (``ORDER_IN_PREPARE`` / ``ORDER_READY`` /
                        ``ORDER_COMPLETED`` / ``ORDER_CANCELLED``
                        …). Useful for partners to filter active
                        vs historical orders without cross-checking
                        timestamps.

Pass-through plus the partner-facing projection. The endpoint that
emits this is ``GET /api/partner/orders`` — see
``routers/partner.py``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.orders import OrderItem, OrderItemInfo


class PartnerOrderItem(BaseModel):
    """One line-item in the partner-facing payload.

    Subset of ``OrderItem`` — only the three fields a partner cares
    about (name + quantity + price-display). We drop modifier IDs,
    weights, and original-list-price because the operator did not
    ask for those (the spec is "tên món + số lượng + giá").

    Wire keys: ``name`` / ``quantity`` / ``priceDisplay``.
    """

    model_config = ConfigDict(populate_by_name=True)

    name: str = ""
    quantity: int = 0
    price_display: str = Field(default="0", alias="priceDisplay")

    @classmethod
    def from_order_item(cls, item: OrderItem) -> "PartnerOrderItem":
        return cls(
            name=item.name,
            quantity=item.quantity,
            priceDisplay=item.price_display or "0",
        )


class PartnerOrder(BaseModel):
    """One order in the partner-facing payload.

    Wire shape (camelCase aliases per the dashboard convention):
      {
        "orderId":     "0010...",
        "displayId":   "GF-00100498847-C8C...",
        "customerName": "Nguyễn Văn A",
        "phone":       "+84 ...",
        "items":       [{"name": "Phở bò", "quantity": 1, "priceDisplay": "65.000"}, …],
        "price":       "65.000",
        "source":      "GF Đà Nẵng",
        "state":       "ORDER_IN_PREPARE",
        "orderedAt":   "2026-08-04T14:46:01Z",
      }
    """

    model_config = ConfigDict(populate_by_name=True)

    order_id: str = Field(alias="orderId")
    display_id: str = Field(default="", alias="displayId")
    customer_name: str = Field(default="", alias="customerName")
    phone: str = ""
    items: list[PartnerOrderItem] = Field(default_factory=list)
    price: str = ""
    source: str = ""
    state: str = ""
    ordered_at: str = Field(default="", alias="orderedAt")

    @classmethod
    def from_archive_row(
        cls,
        *,
        order_id: str,
        display_id: str,
        state: str,
        ordered_at: str,
        payload: dict[str, Any],
        region: str,
        is_anonymised: bool,
    ) -> "PartnerOrder":
        """Project one archive row's ``detail_json`` into the wire shape.

        ``is_anonymised`` is the same flag the dashboard uses
        (``name == "***" and phone == ""``); when true we surface
        empty customer / phone to the partner so they never see
        Grab's anonymisation marker.
        """
        order = payload.get("order") if isinstance(payload.get("order"), dict) else payload
        if not isinstance(order, dict):
            order = {}

        eater = order.get("eater") if isinstance(order.get("eater"), dict) else {}
        if not isinstance(eater, dict):
            eater = {}

        fare = order.get("fare") if isinstance(order.get("fare"), dict) else {}
        if not isinstance(fare, dict):
            fare = {}

        item_info_raw = order.get("itemInfo") if isinstance(order.get("itemInfo"), dict) else {}
        if not isinstance(item_info_raw, dict):
            item_info_raw = {}
        try:
            item_info = OrderItemInfo.model_validate({
                "count": item_info_raw.get("count", 0),
                "items": item_info_raw.get("items") or [],
            })
        except Exception:
            item_info = OrderItemInfo()

        items = [PartnerOrderItem.from_order_item(it) for it in item_info.items]

        if is_anonymised:
            customer_name = ""
            phone = ""
        else:
            raw_name = eater.get("name") or ""
            customer_name = "" if raw_name == "***" else str(raw_name)
            phone = str(eater.get("mobileNumber") or "")

        # Source: "GF " + region. Empty region → just "GF " so the
        # operator can still see which orders came from this PulseOrder
        # instance (vs orders they pulled directly from Grab).
        prefix = "GF"
        if region:
            source = f"{prefix} {region}"
        else:
            source = prefix

        return cls(
            orderId=order_id,
            displayId=display_id,
            customerName=customer_name,
            phone=phone,
            items=items,
            price=str(fare.get("totalDisplay") or "0"),
            source=source,
            state=state,
            orderedAt=ordered_at,
        )


class PartnerOrdersResponse(BaseModel):
    """Envelope for ``GET /api/partner/orders``.

    Same three-list fan-out pattern as ``CustomersOverviewResponse``
    but with a single ``orders`` list (partners want one stream of
    orders, not customers / sources / orders split). Each entry is
    a flat ``PartnerOrder`` with the five fields the operator
    promised to grant a partner access to.
    """

    model_config = ConfigDict(populate_by_name=True)

    orders: list[PartnerOrder] = Field(default_factory=list)
    count: int = 0


# ── Admin (cookie auth) — issue / list / revoke partner keys ────────────────


class CreatePartnerApiKeyRequest(BaseModel):
    """Body for ``POST /api/partner/keys``.

    ``label`` is a human-readable note (e.g. ``"Posmate integration"``)
    so the operator can identify which key is which after they've
    issued a few. Empty label is allowed — the key still works.

    ``merchant_id`` identifies the store the key is scoped to.
    Required because one operator may own many stores and wants
    to grant each partner access to a single branch.
    """

    model_config = ConfigDict(populate_by_name=True)

    merchant_id: str = Field(alias="merchantId")
    label: str = ""


class PartnerApiKeySummary(BaseModel):
    """One row in the operator's "issued keys" list.

    Deliberately excludes ``key_hash`` and the plaintext key — by
    the time we list keys on the dashboard, the plaintext was only
    ever returned once (in the response to ``POST .../keys``) and
    is gone. Listing keys again is for auditing only.

    ``lastUsedAt`` is ``null`` when the key has never been called
    since issue.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: int = 0
    store_id: int = Field(alias="storeId")
    key_prefix: str = Field(alias="keyPrefix")
    label: str = ""
    created_at: datetime = Field(alias="createdAt")
    last_used_at: datetime | None = Field(default=None, alias="lastUsedAt")
    revoked_at: datetime | None = Field(default=None, alias="revokedAt")


class PartnerApiKeyCreatedResponse(BaseModel):
    """Response shape for ``POST /api/partner/keys``.

    **Security contract**: the ``plaintextKey`` is the ONLY time the
    full key is ever returned. We never store it; once the operator
    navigates away from the dashboard's "your new API key" banner,
    the plaintext is gone forever. Revoke + re-issue if lost.

    The summary block is the same as ``PartnerApiKeySummary`` so the
    frontend can refresh its "issued keys" list without a second
    round-trip.
    """

    model_config = ConfigDict(populate_by_name=True)

    plaintext_key: str = Field(alias="plaintextKey")
    summary: PartnerApiKeySummary

