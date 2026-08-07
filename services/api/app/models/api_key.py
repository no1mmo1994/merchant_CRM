"""Per-store partner API key model.

One row per issued partner API key. Multiple keys can exist for the
same Store (one per partner); each key has its own `label` (e.g.
"FoodMap VN", "Posmate") so the operator can revoke a single
partner's access without rotating everyone else's key.

Auth design:
  * `key_prefix` — first 8 chars of the opaque key
    (e.g. `"pulse_" + first 8 of the secret`). Indexed for O(1)
    lookup. NEVER the full key.
  * `key_hash` — bcrypt-hashed full key (`bcrypt.hashpw(...)`).
    Used to verify the caller's presented key against the stored
    hash. NEVER plaintext.

Wire flow on issue:
  1. Operator clicks "Cấp API cho đối tác" on a store.
  2. Backend generates `"pulse_" + secrets.token_urlsafe(32)`.
  3. Backend writes StoreApiKey with `key_prefix` and the bcrypt
     hash; returns the plaintext key ONCE (operator never sees it
     again — it's gone after the response).
  4. Partner sends `Authorization: Bearer <plaintext>` on every
     call. Backend looks up by prefix, bcrypt-verifies, and grants
     access to orders for the store.

Revocation is a soft-delete (`revoked_at`) so audit logs still have
the key id without it staying live. `last_used_at` is updated on
every successful auth for the "did anyone use this?" indicator.
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel


class StoreApiKey(SQLModel, table=True):
    """One issued partner API key for a single store."""

    __tablename__ = "store_api_keys"

    id: int | None = Field(default=None, primary_key=True)
    store_id: int = Field(foreign_key="stores.id", index=True)
    # First 8 characters of the opaque key (e.g. ``"pulse_zz"``).
    # Indexed so the partner endpoint can look up by prefix in O(1)
    # without scanning every key in the DB.
    key_prefix: str = Field(index=True)
    # bcrypt hash of the full opaque key. ``bcrypt.checkpw`` is the
    # verification path. NEVER log this field — even hashed, it's
    # sensitive enough to slow down an offline brute-force.
    key_hash: str = Field()
    # Human-readable label so the operator can keep track of which
    # key was issued to which partner ("Posmate", "FoodMap VN").
    # Empty is allowed.
    label: str = Field(default="")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    # Set on every successful bearer-token auth. Lets the operator
    # see "this key was used 3 minutes ago" without keeping request
    # logs around forever.
    last_used_at: datetime | None = Field(default=None)
    # Soft-delete: once set, the key is dead — no bcrypt check can
    # succeed (we also explicitly short-circuit when reading). We
    # keep the row so the audit log preserves the issue date and
    # the operator can see "this key was revoked on …".
    revoked_at: datetime | None = Field(default=None)
