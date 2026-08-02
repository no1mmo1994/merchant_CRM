"""Menu retrieval endpoint."""

from grab.client import GrabClient


async def get_full_menu(client: GrabClient) -> dict:
    """GET /food/merchant/v2/menu — full menu tree.

    The `orderID` and `oosItemID` query parameters are kept empty by
    default; they only matter when validating an in-flight order.
    """
    res = await client.get(
        "/food/merchant/v2/menu",
        params={"orderID": "", "oosItemID": ""},
    )
    res.raise_for_status()
    return res.json()
