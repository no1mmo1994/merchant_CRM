"""Smoke test: orders endpoints with the real merchant token.

Mirrors `smoke_finance.py`. Hits the FastAPI app via httpx ASGITransport
to skip the dev cookie flow but still exercise the routers end-to-end.
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient
from sqlmodel import Session, select

from app.core.config import settings
from app.deps import _get_session, require_user, get_grab_client
from app.main import app
from app.models import Store, User


async def main() -> None:
    # Pull the seeded user + store so we can impersonate
    with next(_get_session()) as session:
        user = session.exec(select(User)).first()
        store = session.exec(select(Store)).first()
        if not user or not store:
            print("NO USER OR STORE")
            return
        user_id = user.id
        store_id = store.id

    # Override require_user so we don't need a session cookie
    from app.models import User as UserModel
    async def _fake_require_user() -> UserModel:
        with next(_get_session()) as s:
            return s.get(UserModel, user_id)  # type: ignore[arg-type]

    app.dependency_overrides[require_user] = _fake_require_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r1 = await client.get("/api/orders")
            print("=== /api/orders ===")
            print("status:", r1.status_code)
            data = r1.json() if r1.status_code == 200 else None
            if data:
                print(f"page_type={data.get('page_type')}")
                print(f"warnings={data.get('warnings')}")
                orders = data.get("orders") or []
                print(f"orders count: {len(orders)}")
                if orders:
                    first = orders[0]
                    print(f"first.order_id={first.get('order_id')}")
                    print(f"first.display_id={first.get('display_id')}")
                    print(f"first.eater.name={first.get('eater', {}).get('name')}")
                    print(f"first.eater.mobile={first.get('eater', {}).get('mobile_number')}")
                    print(f"first.eater.address={first.get('eater', {}).get('address')[:60] if first.get('eater', {}).get('address') else None}")
                    print(f"first.eater.comment={first.get('eater', {}).get('comment')}")
                    print(f"first.item_info.count={first.get('item_info', {}).get('count')}")
                    items = first.get("item_info", {}).get("items") or []
                    print(f"first.item_info.items: {len(items)}")
                    if items:
                        it = items[0]
                        print(f"  first item: name={it.get('name')!r} qty={it.get('quantity')} price={it.get('price_display')}")
                        mods = it.get("modifier_groups") or []
                        print(f"  modifier_groups: {len(mods)}")
                        for g in mods:
                            print(f"    group {g.get('modifier_group_name')!r}: {len(g.get('modifiers') or [])} mods")
                            for m in (g.get("modifiers") or [])[:3]:
                                print(f"      - {m.get('modifier_name')!r} x{m.get('quantity')} {m.get('price_display')}")
                    print(f"first.fare.total_display={first.get('fare', {}).get('total_display')}")
                    print(f"first.state={first.get('state')}")
                    print(f"first.mex_opt.is_delayed={first.get('mex_opt', {}).get('is_preparation_task_delayed')}")
                    print(f"first.times.created_at={first.get('times', {}).get('created_at')}")

                    oid = first.get("order_id")
                    if oid:
                        r2 = await client.get(f"/api/orders/{oid}")
                        print(f"\n=== /api/orders/{oid} ===")
                        print(f"status: {r2.status_code}")
                        d = r2.json()
                        print(f"detail matches list: {d.get('order_id') == first.get('order_id')}")
                        print(f"detail.item_info.items count: {len(d.get('item_info', {}).get('items') or [])}")
    finally:
        app.dependency_overrides.clear()


asyncio.run(main())
