"""Tests for profile endpoints."""

from __future__ import annotations

import httpx
import pytest
import respx

from grab.client import GrabClient
from grab.endpoints import profile


@pytest.mark.asyncio
@respx.mock
async def test_get_user_profile(authn_token: str, merchant_id: str) -> None:
    respx.get("https://api.grab.com/mex-app/troy/user-profile/v2/details").mock(
        return_value=httpx.Response(
            200,
            json={
                "user_profile": {
                    "merchant_grab_id": "5-C6VKAT5GRK3CTT",
                    "role": "OWNER",
                    "profile_status": "ACTIVE",
                    "user_profile_details": {"first_name": "Test Store"},
                }
            },
        )
    )

    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        data = await profile.get_user_profile(c)

    assert data["user_profile"]["merchant_grab_id"] == "5-C6VKAT5GRK3CTT"


@pytest.mark.asyncio
@respx.mock
async def test_get_unified_profile(authn_token: str, merchant_id: str) -> None:
    respx.get(
        "https://api.grab.com/mex-app/troy/user-profile/v1/unified-profile",
        params__contains={"isBalanceNeeded": "false"},
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "grab_food_profile": {
                        "merchant": {
                            "name": "Test Store",
                            "address": "123 Test St",
                            "status": "ACTIVE",
                        }
                    }
                }
            },
        )
    )

    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        data = await profile.get_unified_profile(c)

    assert data["data"]["grab_food_profile"]["merchant"]["name"] == "Test Store"


@pytest.mark.asyncio
@respx.mock
async def test_get_store_list(authn_token: str, merchant_id: str) -> None:
    respx.get("https://api.grab.com/mex-app/troy/user-profile/v1/store-list").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "stores": [
                        {"gpid": "1", "name": "Store A"},
                        {"gpid": "2", "name": "Store B"},
                    ]
                }
            },
        )
    )

    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        data = await profile.get_store_list(c)

    assert len(data["data"]["stores"]) == 2