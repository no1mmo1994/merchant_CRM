"""Menu router — fetch full menu."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.deps import get_grab_client
from app.schemas import MenuResponse
from grab.endpoints.menu import get_full_menu

router = APIRouter(prefix="/api/menu", tags=["menu"])


@router.get("", response_model=MenuResponse)
@router.get("/", response_model=MenuResponse)
async def get_menu(
    client=Depends(get_grab_client),
) -> MenuResponse:
    """Return the full Grab menu for the active store."""
    menu = await get_full_menu(client)
    return MenuResponse(menu=menu)
