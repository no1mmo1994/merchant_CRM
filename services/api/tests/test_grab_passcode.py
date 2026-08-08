"""Grab gating every menu write behind a merchant passcode.

Measured against the live store on 2026-08-08: linking a modifier group
to an item, creating / editing / deleting a group, creating or deleting a
category, and reordering categories all answer

    403 {"target":"ErrPasscodeForbidden","reason":"forbidden",
         "message":"Token not valid"}

while reads (`/v2/menu`, `menu-translations`) and the menu-edit lock all
still answer 200. So it is the credential, not the request — and the
operator has to be told that, because the surface it breaks looks like a
dozen unrelated features failing at once.

Two ways of getting this wrong that these tests pin:

  * reporting it as "HTTP 403" per item, which reads as a fault in the
    item — the operator's actual report was "can't link items", when
    nothing about the items or the link was wrong;
  * reporting it as an expired login, which sends them to re-authenticate
    — a fresh login mints the same token and hits the same wall.
"""

from __future__ import annotations

from app.core.grab_errors import PASSCODE_TARGET, is_passcode_error

PASSCODE_BODY = {
    "target": "ErrPasscodeForbidden",
    "reason": "forbidden",
    "message": "Token not valid",
}


class TestIsPasscodeError:
    def test_recognises_the_live_envelope(self) -> None:
        assert is_passcode_error(403, PASSCODE_BODY) is True
        # Callers hand it either the parsed dict or the raw text.
        assert is_passcode_error(
            403, '{"target":"ErrPasscodeForbidden","reason":"forbidden"}'
        ) is True

    def test_matched_on_target_not_on_status(self) -> None:
        """A 403 alone means several things.

        Grab's `message` here is "Token not valid", which reads exactly
        like an expired session — the one conclusion that would waste the
        operator's time, because logging in again produces the same
        token.
        """
        assert is_passcode_error(403, {"target": "ErrSomethingElse"}) is False
        assert is_passcode_error(403, {"message": "Token not valid"}) is False

    def test_other_statuses_are_not_passcode_errors(self) -> None:
        assert is_passcode_error(401, PASSCODE_BODY) is False
        assert is_passcode_error(409, PASSCODE_BODY) is False

    def test_unparseable_bodies_are_safe(self) -> None:
        assert is_passcode_error(403, "") is False
        assert is_passcode_error(403, "<html>gateway</html>") is False
        assert is_passcode_error(403, None) is False
        assert is_passcode_error(403, ["not", "a", "dict"]) is False

    def test_target_constant_matches_what_grab_sends(self) -> None:
        assert PASSCODE_TARGET == PASSCODE_BODY["target"]
