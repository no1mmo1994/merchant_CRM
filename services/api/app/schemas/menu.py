"""Pydantic schemas for menu endpoints."""

from __future__ import annotations

from pydantic import BaseModel


class MenuResponse(BaseModel):
    menu: dict
