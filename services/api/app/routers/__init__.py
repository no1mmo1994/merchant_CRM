"""Re-export all routers for convenient top-level imports."""

from __future__ import annotations

from app.routers.audit import router as audit_router
from app.routers.auth import router as auth_router
from app.routers.categories import router as categories_router
from app.routers.customers import router as customers_router
from app.routers.finance import router as finance_router
from app.routers.items import router as items_router
from app.routers.menu import router as menu_router
from app.routers.modifiers import router as modifiers_router
from app.routers.orders import router as orders_router
from app.routers.partner import router as partner_router
from app.routers.stores import router as stores_router

__all__ = [
    "audit_router",
    "auth_router",
    "categories_router",
    "customers_router",
    "finance_router",
    "items_router",
    "menu_router",
    "modifiers_router",
    "orders_router",
    "partner_router",
    "stores_router",
]
