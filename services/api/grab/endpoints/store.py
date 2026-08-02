"""Store metadata endpoints (business attributes, scorecard)."""

from grab.client import GrabClient


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
