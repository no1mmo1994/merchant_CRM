"""Extract the city/province from a Vietnamese merchant address.

Grab's unified-profile endpoint returns addresses as a comma-separated
string in Vietnamese. The standard form is::

    <street>, <ward/commune>, <district>, <city/province>

Examples the dashboard has seen in production:
  * "110 Hà Duy Phiên, Hòa Châu, Hòa Vang"     → "Đà Nẵng"
  * "12 Nguyễn Huệ, Bến Nghé, Quận 1, TP.HCM"   → "TP.HCM"
  * "35 Phan Đình Phùng, Quán Thánh, Ba Đình"   → "Hà Nội"

This module exposes one helper — ``extract_city(address)`` — that
returns the city/province label the partner API uses to prefix the
``source`` field (`"GF " + region`).

Strategy:

1. Split on commas, trim each segment.
2. Walk the segments right-to-left looking for one that matches a
   known district name in ``_DISTRICT_TO_CITY``. Districts are
   unique within Vietnam — each district belongs to exactly one
   city/province — so the lookup is unambiguous.
3. If no district match, check each segment against ``_CITY_ALIASES``
   directly (handles addresses that omit the district, e.g.
   "35 Phan Đình Phùng, Quán Thánh, Ba Đình" where the city
   "Hà Nội" isn't in the address at all — for that case we still
   fall back to the district lookup because "Ba Đình" maps to
   "Hà Nội").
4. Return the original address string untouched as the final
   fallback so callers never see an empty region — better to show
   the whole address than nothing.

Why a static dict (not a DB table):

  * Vietnamese administrative geography changes slowly (every few
    years). A dict in source code is easy to update in one PR.
  * The cost of an out-of-date district is one wrong region label
    — never a security or correctness issue.
  * Avoids a JOIN on every region-extraction call (the partner API
    hits this on every order it surfaces).
"""

from __future__ import annotations

import re
from typing import Final

# Canonical city/province labels used in the ``source`` field.
# Keep the diacritics — the dashboard renders them verbatim and the
# partner API's payload is consumed by humans, not a sortable enum.
HCM_CITY: Final = "TP.HCM"
HANOI_CITY: Final = "Hà Nội"
DANANG_CITY: Final = "Đà Nẵng"
HAIPHONG_CITY: Final = "Hải Phòng"
CANTHO_CITY: Final = "Cần Thơ"

# District → city map. Covers the major districts of the five
# centrally-governed cities plus the most common provinces for
# the Grab-merchant food delivery market (Đà Nẵng, HCM, Hà Nội,
# Hải Phòng, Cần Thơ, plus Bình Dương / Đồng Nai / Khánh Hoà /
# Bà Rịa-Vũng Tàu / Long An / Bình Phước for the HCMC metro +
# tourism hubs). Add entries here as new districts come up — the
# fallback chain below handles the unknown cases gracefully.
_DISTRICT_TO_CITY: Final[dict[str, str]] = {
    # ── Đà Nẵng ────────────────────────────────────────────────
    "Hòa Vang": DANANG_CITY,
    "Hải Châu": DANANG_CITY,
    "Thanh Khê": DANANG_CITY,
    "Sơn Trà": DANANG_CITY,
    "Ngũ Hành Sơn": DANANG_CITY,
    "Liên Chiểu": DANANG_CITY,
    "Cẩm Lệ": DANANG_CITY,
    # ── TP.HCM ─────────────────────────────────────────────────
    "Quận 1": HCM_CITY,
    "Quận 3": HCM_CITY,
    "Quận 4": HCM_CITY,
    "Quận 5": HCM_CITY,
    "Quận 6": HCM_CITY,
    "Quận 7": HCM_CITY,
    "Quận 8": HCM_CITY,
    "Quận 10": HCM_CITY,
    "Quận 11": HCM_CITY,
    "Quận 12": HCM_CITY,
    "Quận Bình Thạnh": HCM_CITY,
    "Quận Phú Nhuận": HCM_CITY,
    "Quận Tân Bình": HCM_CITY,
    "Quận Tân Phú": HCM_CITY,
    "Quận Gò Vấp": HCM_CITY,
    "Quận Bình Tân": HCM_CITY,
    "Thành phố Thủ Đức": HCM_CITY,
    "Huyện Bình Chánh": HCM_CITY,
    "Huyện Hóc Môn": HCM_CITY,
    "Huyện Củ Chi": HCM_CITY,
    "Huyện Nhà Bè": HCM_CITY,
    "Huyện Cần Giờ": HCM_CITY,
    # ── Hà Nội ─────────────────────────────────────────────────
    "Ba Đình": HANOI_CITY,
    "Hoàn Kiếm": HANOI_CITY,
    "Hai Bà Trưng": HANOI_CITY,
    "Đống Đa": HANOI_CITY,
    "Tây Hồ": HANOI_CITY,
    "Cầu Giấy": HANOI_CITY,
    "Thanh Xuân": HANOI_CITY,
    "Hoàng Mai": HANOI_CITY,
    "Long Biên": HANOI_CITY,
    "Hà Đông": HANOI_CITY,
    "Bắc Từ Liêm": HANOI_CITY,
    "Nam Từ Liêm": HANOI_CITY,
    # ── Hải Phòng ──────────────────────────────────────────────
    "Hồng Bàng": HAIPHONG_CITY,
    "Lê Chân": HAIPHONG_CITY,
    "Ngô Quyền": HAIPHONG_CITY,
    "Kiến An": HAIPHONG_CITY,
    "Hải An": HAIPHONG_CITY,
    # ── Cần Thơ ────────────────────────────────────────────────
    "Ninh Kiều": CANTHO_CITY,
    "Bình Thủy": CANTHO_CITY,
    "Cái Răng": CANTHO_CITY,
    # ── Bình Dương ────────────────────────────────────────────
    "Thủ Dầu Một": "Bình Dương",
    "Dĩ An": "Bình Dương",
    "Thuận An": "Bình Dương",
    # ── Đồng Nai ───────────────────────────────────────────────
    "Thành phố Biên Hòa": "Đồng Nai",
    "Long Khánh": "Đồng Nai",
    # ── Khánh Hoà (Nha Trang) ─────────────────────────────────
    "Thành phố Nha Trang": "Khánh Hoà",
    "Cam Ranh": "Khánh Hoà",
    # ── Bà Rịa - Vũng Tàu ─────────────────────────────────────
    "Thành phố Vũng Tàu": "Bà Rịa - Vũng Tàu",
    "Thành phố Bà Rịa": "Bà Rịa - Vũng Tàu",
}

# Direct city/province aliases — handles addresses that already
# contain the city name verbatim (no need to walk back to a district).
# Keys are normalised (lower + strip) for the lookup; values are the
# canonical city label.
_CITY_ALIASES: Final[dict[str, str]] = {
    "tp.hcm": HCM_CITY,
    "tp hcm": HCM_CITY,
    "thành phố hồ chí minh": HCM_CITY,
    "thành phố hcm": HCM_CITY,
    "hồ chí minh": HCM_CITY,
    "hcm": HCM_CITY,
    "hà nội": HANOI_CITY,
    "hn": HANOI_CITY,
    "đà nẵng": DANANG_CITY,
    "dn": DANANG_CITY,
    "hải phòng": HAIPHONG_CITY,
    "cần thơ": CANTHO_CITY,
    "bình dương": "Bình Dương",
    "đồng nai": "Đồng Nai",
    "khánh hoà": "Khánh Hoà",
    "bà rịa - vũng tàu": "Bà Rịa - Vũng Tàu",
    "bà rịa vũng tàu": "Bà Rịa - Vũng Tàu",
    "vũng tàu": "Bà Rịa - Vũng Tàu",
    "long an": "Long An",
    "bình phước": "Bình Phước",
}

# Strip leading prefixes that Grab sometimes prepends to the
# address field. "Tỉnh ", "Thành phố ", "TP." all signal the next
# segment is a city — for the alias check we want to strip them.
_LEADING_PREFIX_RE: Final = re.compile(r"^\s*(?:Tỉnh|Thành phố|TP\.?|Tp\.?)\s+")


def _normalise_segment(segment: str) -> str:
    """Lower-case + strip + drop "Tỉnh/Thành phố/TP" prefix.

    Used only for the alias-table lookup; the canonical city label
    we return preserves the user's diacritics.
    """
    s = segment.strip()
    s = _LEADING_PREFIX_RE.sub("", s)
    return s.lower()


def _split_segments(address: str) -> list[str]:
    """Split a Grab-style address on commas, trim each segment, drop empties."""
    if not isinstance(address, str):
        return []
    return [s.strip() for s in address.split(",") if s and s.strip()]


def extract_city(address: str | None) -> str:
    """Return the city/province label for a Vietnamese merchant address.

    Resolution order:
      1. Empty / non-string input → ``""`` (the caller falls back to
         the raw address string).
      2. Walk the comma-separated segments right-to-left. The first
         segment that matches a known district name in
         ``_DISTRICT_TO_CITY`` wins — districts are unique within
         Vietnam, so the lookup is unambiguous.
      3. Walk the same segments looking for a city alias — handles
         addresses that contain the city verbatim and skip the
         district (rare for Grab, common for hand-typed addresses).
      4. Return the original address string verbatim so the
         dashboard still has something to render.

    The function is pure — no DB, no I/O — so it is safe to call
    on every partner-API request.
    """
    if not address or not isinstance(address, str):
        return ""
    raw = address.strip()
    if not raw:
        return ""

    segments = _split_segments(raw)
    if not segments:
        return ""

    # Step 2: district → city (right-to-left). The address form is
    # `street, ward, district, [city]` — the city is usually the
    # right-most segment, but we walk the whole list because some
    # addresses drop the city entirely (city implied by district).
    for seg in reversed(segments):
        if seg in _DISTRICT_TO_CITY:
            return _DISTRICT_TO_CITY[seg]

    # Step 3: direct city alias. Helps when Grab puts "HCM" / "TP.HCM"
    # at the end of the address instead of a district.
    for seg in segments:
        norm = _normalise_segment(seg)
        if norm in _CITY_ALIASES:
            return _CITY_ALIASES[norm]

    # Step 4: best-effort fallback — return the last non-empty
    # segment. Better than nothing; the partner API's `source`
    # field will at least surface something.
    return segments[-1]
