"""Tests for ``app.core.region.extract_city``.

Pure-function tests — no DB, no FastAPI. Each address we care
about is in its own test so the failure message tells the operator
which case regressed (e.g. "did Đà Nẵng break again?").
"""

from __future__ import annotations

import pytest

from app.core.region import (
    DANANG_CITY,
    HCM_CITY,
    HANOI_CITY,
    extract_city,
)


# ── primary cases: the operator's literal production data ────────────────────


def test_extract_city_danang_hoa_vang() -> None:
    """The exact production address the operator reported.

    The store at "110 Hà Duy Phiên, Hòa Châu, Hòa Vang" must
    resolve to "Đà Nẵng" — Hòa Vang is a rural district of Đà Nẵng
    city. This is the round-5 requirement verbatim.
    """
    assert extract_city("110 Hà Duy Phiên, Hòa Châu, Hòa Vang") == DANANG_CITY


def test_extract_city_danang_districts() -> None:
    """All seven Đà Nẵng districts must round-trip to Đà Nẵng."""
    cases = [
        "12 Lê Duẩn, Hải Châu",
        "35 Trần Phú, Thanh Khê",
        "45 Ngô Quyền, Sơn Trà",
        "Trần Hưng Đạo, Ngũ Hành Sơn",
        "Tôn Đức Thắng, Liên Chiểu",
        "Lê Thánh Tông, Cẩm Lệ",
        "Quốc lộ 1A, Hòa Vang",
    ]
    for addr in cases:
        assert extract_city(addr) == DANANG_CITY, addr


# ── other centrally-governed cities ────────────────────────────────────────


def test_extract_city_hcm_districts() -> None:
    """Quận / Huyện / Thành phố Thủ Đức prefixes."""
    assert extract_city("1 Lê Lợi, Quận 1, TP.HCM") == HCM_CITY
    assert extract_city("Lý Chính Thắng, Quận 3") == HCM_CITY
    assert extract_city("Lê Văn Sỹ, Quận Phú Nhuận") == HCM_CITY
    assert extract_city("Cách Mạng Tháng 8, Quận Tân Bình") == HCM_CITY
    assert extract_city("Võ Văn Ngân, Thành phố Thủ Đức") == HCM_CITY


def test_extract_city_hanoi_districts() -> None:
    """Hà Nội — the most common province for food delivery."""
    assert (
        extract_city("35 Phan Đình Phùng, Quán Thánh, Ba Đình")
        == HANOI_CITY
    )
    assert (
        extract_city("Tràng Tiền, Hoàn Kiếm")
        == HANOI_CITY
    )
    assert extract_city("Bạch Mai, Hai Bà Trưng") == HANOI_CITY


# ── city-alias only path (no district) ──────────────────────────────────────


def test_extract_city_city_alias_only() -> None:
    """When the address skips the district and just names the city."""
    assert extract_city("Đường ABC, Phường X, Hà Nội") == HANOI_CITY
    assert extract_city("Đường ABC, TP.HCM") == HCM_CITY
    assert extract_city("Đường ABC, Đà Nẵng") == DANANG_CITY


# ── empty + malformed input ─────────────────────────────────────────────────


def test_extract_city_empty_strings() -> None:
    """Empty / non-string input → empty string (never raises)."""
    assert extract_city("") == ""
    assert extract_city(None) == ""
    assert extract_city("   ") == ""


def test_extract_city_commas_only() -> None:
    """A string of just commas → empty after stripping → empty string."""
    assert extract_city(",,,") == ""


# ── unknown-district fallback ───────────────────────────────────────────────


def test_extract_city_unknown_district_returns_last_segment() -> None:
    """A district not in the dict — return last segment verbatim.

    Better than nothing: the dashboard's SourceCard has *something*
    to render on the subtitle, and the partner API's `source`
    field still surfaces a non-empty label.
    """
    # "Huyện XYZ" isn't in the table — fall back to the last segment.
    assert extract_city("Đường ABC, Huyện XYZ") == "Huyện XYZ"


# ── prefix-stripping robustness ─────────────────────────────────────────────


def test_extract_city_prefix_stripping() -> None:
    """"Thành phố Hồ Chí Minh" segment should still resolve to TP.HCM.

    Some Grab regional payloads prepend "Thành phố " to the city.
    Our ``_normalise_segment`` helper strips that before lookup —
    this test guards against a future refactor that loses the
    regex.
    """
    assert extract_city("Đường ABC, Thành phố Hồ Chí Minh") == HCM_CITY


# ── regression: did not break for non-extraordinary cases ─────────────────


@pytest.mark.parametrize(
    "addr,expected",
    [
        # ── Đà Nẵng metropolitan ──
        ("110 Hà Duy Phiên, Hòa Châu, Hòa Vang", "Đà Nẵng"),
        ("Hải Châu", "Đà Nẵng"),
        ("Sơn Trà", "Đà Nẵng"),
        # ── TP.HCM ──
        ("Quận 1, TP.HCM", "TP.HCM"),
        ("Quận Bình Thạnh", "TP.HCM"),
        ("Thành phố Thủ Đức", "TP.HCM"),
        # ── Hà Nội ──
        ("Ba Đình, Hà Nội", "Hà Nội"),
        ("Hoàn Kiếm", "Hà Nội"),
        # ── Surrounding provinces (HCMC metro / tourism) ──
        ("Dĩ An, Bình Dương", "Bình Dương"),
        ("Thành phố Biên Hòa, Đồng Nai", "Đồng Nai"),
        ("Thành phố Nha Trang, Khánh Hoà", "Khánh Hoà"),
        # ── Alias-only ──
        ("Quán Thánh, Ba Đình, Hà Nội", "Hà Nội"),
        ("Quán Thánh, Ba Đình", "Hà Nội"),  # city implicit
    ],
)
def test_extract_city_table_driven(addr: str, expected: str) -> None:
    """Parametrised safety-net — runs every case through ``extract_city``."""
    assert extract_city(addr) == expected, addr
