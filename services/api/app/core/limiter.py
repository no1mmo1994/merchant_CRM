"""Shared SlowAPI limiter instance — imported by routers and main."""

from slowapi import Limiter
from slowapi.util import get_remote_address

# Module-level limiter keyed by client IP. Routers and main.py both import this.
limiter = Limiter(key_func=get_remote_address)
