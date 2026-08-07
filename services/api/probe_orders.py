"""Probe live Grab orders endpoints with the merchant's real token.

Dumps the raw JSON so we know what shape to model on the dashboard.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime, timedelta

from cryptography.fernet import Fernet
from sqlmodel import Session, select

from app.core.config import settings
from app.deps import _get_session
from app.models import Store
from grab.client import GrabClient


async def main() -> None:
    with next(_get_session()) as session:
        store = session.exec(select(Store)).first()
        if not store:
            print("NO STORE")
            return
        fernet = Fernet(settings.token_encryption_key.encode())
        token = fernet.decrypt(store.encrypted_auth_token.encode()).decode()
        merchant_id = store.merchant_id

    async with GrabClient(authn_token=token, merchant_id=merchant_id) as client:
        # 1) List preparing orders
        url = "/food/merchant/v3/orders-pagination"
        params = {"pageType": "Preparing", "autoAcceptGroup": "1", "timestamp": ""}
        res = await client.get(url, params=params)
        body = res.json() if res.status_code == 200 else {"raw": res.text[:500]}
        print("=== LIST status", res.status_code, "===")
        orders = body.get("orders") or body.get("data") or []
        print(f"orders count: {len(orders)}")
        if orders:
            first = orders[0]
            print("first order keys:", list(first.keys())[:30] if isinstance(first, dict) else type(first))
            print("first order:", json.dumps(first, ensure_ascii=False, default=str)[:1000])
            order_id = first.get("orderID") or first.get("orderId") or first.get("id")
        else:
            order_id = None
        # Try other pageTypes just in case
        for page_type in ("All", "New", "Ready", "Completed"):
            r = await client.get(
                url,
                params={"pageType": page_type, "autoAcceptGroup": "1", "timestamp": ""},
            )
            d = r.json() if r.status_code == 200 else {}
            cnt = len(d.get("orders") or d.get("data") or [])
            print(f"  pageType={page_type}: count={cnt}")

        # 2) Order detail if we have an order id
        if order_id:
            print(f"\n=== DETAIL order_id={order_id} ===")
            device_time = int(time.time() * 1000)
            res = await client.get(
                f"/food/merchant/v3/orders/{order_id}",
                params={"deviceTimeInMillis": device_time},
            )
            print("status:", res.status_code)
            d = res.json()
            print("top-level keys:", list(d.keys()))
            order = d.get("order", {})
            print("order keys:", list(order.keys()))
            print("eater keys:", list((order.get("eater") or {}).keys()))
            print("itemInfo keys:", list((order.get("itemInfo") or {}).keys()))
            items = (order.get("itemInfo") or {}).get("items") or []
            print(f"item count: {len(items)}")
            if items:
                print("first item keys:", list(items[0].keys())[:30])
                print("first item:", json.dumps(items[0], ensure_ascii=False, default=str)[:800])
            print("\nfare keys:", list((order.get("fare") or {}).keys()))
            print("mexOPT keys:", list((order.get("mexOPT") or {}).keys()))


asyncio.run(main())