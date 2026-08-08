"""Grab error envelopes that mean the same thing everywhere.

Each router maps Grab failures its own way — item uploads care about
aspect ratios, modifier groups about selection ranges. A few refusals
though are about the *credential*, not the request, and they need the
same answer whichever endpoint they arrive on.
"""

from __future__ import annotations

import json
from typing import Any

#: Grab's marker for "this token has not cleared the merchant passcode".
#:
#: Measured against the live store on 2026-08-08: every menu **write**
#: answers `403 {"target":"ErrPasscodeForbidden","reason":"forbidden",
#: "message":"Token not valid"}` — linking a modifier group to an item,
#: creating / editing / deleting a modifier group, creating or deleting a
#: category, and reordering categories. Reads are untouched: `/v2/menu`,
#: `menu-translations` and the menu-edit lock all still answer 200.
#:
#: So it is not the operation being rejected, and not the auth token
#: being expired — it is the whole write surface behind a passcode this
#: dashboard's token was never issued for. Reporting that as a bare
#: "HTTP 403" per item sends the operator looking for a fault in the
#: thing they were editing.
PASSCODE_TARGET = "ErrPasscodeForbidden"

PASSCODE_CODE = "grab_passcode_required"

PASSCODE_MESSAGE = (
    "Grab yêu cầu mã PIN bảo mật cho thao tác sửa thực đơn — không phải lỗi "
    "của món hay nhóm bạn vừa chọn. Grab Merchant gửi mã PIN dưới dạng chuỗi "
    "băm do chính app tạo (không phải chữ số PIN), nên dashboard không thể "
    "tự nhập giúp. Vui lòng thực hiện thao tác sửa thực đơn này trong app "
    "Grab Merchant."
)

#: Short form for a per-row failure list, where the long sentence would be
#: repeated once per item.
PASSCODE_SHORT = "Grab yêu cầu mã PIN"


def _envelope(body: Any) -> dict[str, Any]:
    """Grab's error JSON, or an empty dict when it sent something else."""
    if isinstance(body, dict):
        return body
    if not isinstance(body, str) or not body.strip():
        return {}
    try:
        parsed = json.loads(body)
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def is_passcode_error(status_code: int, body: Any) -> bool:
    """True when Grab refused because the token has no passcode claim.

    Matched on `target`, not on the status: a 403 alone can mean several
    things, and `message` is the English "Token not valid", which reads
    like an expired login and would send the operator to re-authenticate
    — which does not help, because a fresh login produces the same token.
    """
    if status_code != 403:
        return False
    return str(_envelope(body).get("target") or "") == PASSCODE_TARGET
