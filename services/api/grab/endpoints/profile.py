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
