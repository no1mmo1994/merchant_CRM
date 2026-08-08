"""Reading a program's economics out of Grab's Vietnamese prose.

`gms/v1/events/{id}` returns rendered UI, not data: sections keyed by
`uiType`, each with a `params` **JSON string**, and every figure embedded
in a sentence — "Giảm 12.000đ cho đơn hàng", "Grab đồng tài trợ 1.000đ".

That makes the parser the load-bearing piece of the marketing advisor: if
it reads a co-funding share wrong, the dashboard recommends joining a
program that loses the store money on every order. These tests pin the
shapes taken from `marketing/getchitiet_dsmarketing.py` and the failure
modes that would be silent.
"""

from __future__ import annotations

import asyncio
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.core.config import settings
from app.core.security import COOKIE_NAME, SessionToken, encrypt_token
from app.deps import get_session
from app.main import app
from app.models import Store, User  # noqa: F401  (registers tables)
from app.routers.marketing import _attach_funding
from app.schemas.marketing import (
    SpotlightEvent,
    find_image_url,
    parse_event_detail,
    parse_money,
    parse_percent,
)


def _section(ui_type: str, params: dict) -> dict:
    """Grab sends `params` as a JSON string, never as an object."""
    return {"uiType": ui_type, "params": json.dumps(params)}


def _lever(sub_items: list[dict], **flags) -> dict:
    return _section(
        "LEVER_ITEM_V2",
        {**flags, "items": [{"title": "Khuyến mại", "subItems": sub_items}]},
    )


class TestParseMoney:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Giảm 12.000đ cho đơn hàng", 12_000),
            ("Giá trị đơn hàng tối thiểu 40.000đ", 40_000),
            ("Grab đồng tài trợ 1.000đ", 1_000),
            ("Giảm 8.000 đ", 8_000),  # space before the currency mark
            ("1.234.567₫", 1_234_567),
            ("Tối đa 50000 VND", 50_000),  # ungrouped digits, uppercase unit
        ],
    )
    def test_reads_vnd_out_of_a_sentence(self, text: str, expected: int) -> None:
        assert parse_money(text) == expected

    def test_absent_figure_is_none_not_zero(self) -> None:
        """The distinction the whole advisor rests on.

        Returning 0 for "no figure here" would make a program whose
        co-funding Grab never stated look like a program where Grab pays
        nothing — and then `discount - cofund` would silently overstate
        the store's burden instead of admitting it is unknown.
        """
        assert parse_money("Áp dụng cho khách hàng mới") is None

    def test_percentage_is_not_read_as_money(self) -> None:
        """"Giảm 50%" must not become 50 đồng."""
        assert parse_money("Giảm 50% cho món") is None

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Áp dụng tối đa 500 đơn hàng, Grab đồng tài trợ 1.000đ", 1_000),
            ("Giảm cho 3 đơn đầu tiên, trị giá 12.000đ", 12_000),
            ("Hỗ trợ 2 đồng hồ vàng, tài trợ 5.000đ", 5_000),
        ],
    )
    def test_vietnamese_words_starting_with_d_are_not_currency(
        self, text: str, expected: int
    ) -> None:
        """"500 đơn hàng" is a count, not 500 đồng.

        Vietnamese is full of words beginning with đ — đơn, đồng, được —
        so a currency pattern that accepts a bare trailing `đ` swallows
        the first letter of the next word. In a CO_FUND bullet that
        substitutes an order-count cap for Grab's actual contribution,
        which is precisely the figure the funding ratio is computed from.
        """
        assert parse_money(text) == expected


class TestParsePercent:
    def test_reads_percentage(self) -> None:
        assert parse_percent("MÓN XỊN GIẢM 50%") == 50.0

    def test_comma_decimal(self) -> None:
        """Vietnamese writes 8,3% where English writes 8.3%."""
        assert parse_percent("Grab gánh 8,3%") == 8.3

    def test_absent_is_none(self) -> None:
        assert parse_percent("Giảm 12.000đ") is None


class TestParseEventDetail:
    def test_derives_the_number_grab_never_states(self) -> None:
        """#B0T1G100: giảm 12.000đ, Grab góp 1.000đ → shop chịu 11.000đ.

        Grab prints the discount and its own contribution on separate
        lines and never subtracts them. 8.3% funding is what a program
        advertised as "đồng tài trợ" actually amounts to, and that only
        becomes visible once the subtraction is done.
        """
        detail = parse_event_detail(
            {
                "eventID": "EVT1",
                "name": "Thúc Đẩy Doanh Số Cơ Bản #B0T1G100",
                "status": "AVAILABLE",
                "isEligible": True,
                "sections": [
                    _lever(
                        [
                            {
                                "title": "Giảm 12.000đ cho đơn hàng",
                                "bullets": [
                                    {
                                        "type": "MOV",
                                        "content": "Giá trị đơn hàng tối thiểu 40.000đ",
                                    },
                                    {
                                        "type": "CO_FUND",
                                        "content": "Grab đồng tài trợ 1.000đ",
                                    },
                                ],
                            }
                        ],
                        isPromoStacking=True,
                        isGrabCoFund=True,
                    )
                ],
            }
        )

        assert detail.event_id == "EVT1"
        assert detail.is_eligible is True
        assert detail.is_promo_stacking is True
        assert detail.is_grab_cofund is True

        (tier,) = detail.tiers
        assert tier.discount_vnd == 12_000
        assert tier.min_order_vnd == 40_000
        assert tier.grab_cofund_vnd == 1_000
        assert tier.merchant_cost_vnd == 11_000
        assert tier.grab_funded_pct == pytest.approx(1_000 / 12_000)

        # Grab's own wording survives alongside the parsed numbers, so a
        # misparse is visible in the UI instead of hidden behind a clean
        # figure.
        assert [b.content for b in tier.bullets] == [
            "Giá trị đơn hàng tối thiểu 40.000đ",
            "Grab đồng tài trợ 1.000đ",
        ]

    def test_title_nested_under_promo(self) -> None:
        """Some rows carry the title as `promo.title` instead of `title`.

        The capture script falls back the same way; missing it would drop
        the discount amount for those tiers and leave them unrankable.
        """
        detail = parse_event_detail(
            {
                "sections": [
                    _lever(
                        [
                            {
                                "promo": {"title": "Giảm 10.000đ cho đơn hàng"},
                                "bullets": [
                                    {
                                        "type": "CO_FUND",
                                        "content": "Grab đồng tài trợ 2.000đ",
                                    }
                                ],
                            }
                        ]
                    )
                ]
            }
        )
        (tier,) = detail.tiers
        assert tier.title == "Giảm 10.000đ cho đơn hàng"
        assert tier.discount_vnd == 10_000
        assert tier.merchant_cost_vnd == 8_000
        assert tier.grab_funded_pct == pytest.approx(0.2)

    def test_percentage_program_invents_no_figures(self) -> None:
        """A "giảm 50%" program has no fixed đồng value.

        The cost depends on the item, so `merchant_cost_vnd` must stay
        None rather than resolve to a number nothing in the payload
        supports.
        """
        detail = parse_event_detail(
            {"sections": [_lever([{"title": "Giảm 50% cho món", "bullets": []}])]}
        )
        (tier,) = detail.tiers
        assert tier.discount_percent == 50.0
        assert tier.discount_vnd is None
        assert tier.merchant_cost_vnd is None
        assert tier.grab_funded_pct is None

    def test_capped_percentage_is_not_flattened_into_a_fixed_discount(self) -> None:
        """"Giảm 20% tối đa 50.000đ" is not a 50.000đ discount.

        The title contains both a percentage and a đồng figure. Reading
        the money as the discount would turn a variable 20% into a
        guaranteed 50.000đ, and the derived merchant cost would then be
        computed off an amount no order actually pays — overstating the
        discount on every order below the cap.
        """
        detail = parse_event_detail(
            {
                "sections": [
                    _lever(
                        [
                            {
                                "title": "Giảm 20% tối đa 50.000đ cho đơn hàng",
                                "bullets": [
                                    {"type": "CO_FUND", "content": "Grab đồng tài trợ 5.000đ"}
                                ],
                            }
                        ]
                    )
                ]
            }
        )
        (tier,) = detail.tiers
        assert tier.discount_percent == 20.0
        assert tier.discount_vnd is None
        assert tier.merchant_cost_vnd is None
        assert tier.grab_funded_pct is None
        # The ceiling is real information — kept, just not mistaken for
        # the discount itself.
        assert tier.discount_cap_vnd == 50_000

    def test_incidental_percent_does_not_destroy_a_flat_discount(self) -> None:
        """A `%` later in the title must not reclassify the tier.

        "Giảm 12.000đ cho đơn hàng, áp dụng 100% thời gian khuyến mãi" is a
        flat 12.000đ tier. Treating any `%` as the discount would call it a
        100%-off tier, demote the real 12.000đ to a "cap", and leave
        `merchant_cost_vnd` unknown — losing precisely the figure this
        feature exists to produce. Whichever figure comes *first* decides.
        """
        detail = parse_event_detail(
            {
                "sections": [
                    _lever(
                        [
                            {
                                "title": "Giảm 12.000đ cho đơn hàng, áp dụng 100% thời gian khuyến mãi",
                                "bullets": [
                                    {"type": "CO_FUND", "content": "Grab đồng tài trợ 1.000đ"}
                                ],
                            }
                        ]
                    )
                ]
            }
        )
        (tier,) = detail.tiers
        assert tier.discount_vnd == 12_000
        assert tier.discount_percent is None
        assert tier.merchant_cost_vnd == 11_000

    def test_cap_is_anchored_to_toi_da_not_to_any_later_amount(self) -> None:
        """A title can name a minimum order *and* a cap.

        "Giảm 20% cho đơn từ 40.000đ, tối đa 50.000đ" — taking "the money
        after the percent" picks 40.000đ, showing a cap 10.000đ below the
        real one. The cap has to be read from the phrase that names it.
        """
        detail = parse_event_detail(
            {
                "sections": [
                    _lever(
                        [
                            {
                                "title": "Giảm 20% cho đơn từ 40.000đ, tối đa 50.000đ",
                                "bullets": [],
                            }
                        ]
                    )
                ]
            }
        )
        (tier,) = detail.tiers
        assert tier.discount_percent == 20.0
        assert tier.discount_cap_vnd == 50_000

    def test_percentage_without_a_stated_cap_reports_none(self) -> None:
        """No "tối đa" phrase → no cap. Never guess one from the sentence."""
        detail = parse_event_detail(
            {
                "sections": [
                    _lever(
                        [{"title": "Giảm 50% cho đơn từ 30.000đ", "bullets": []}]
                    )
                ]
            }
        )
        (tier,) = detail.tiers
        assert tier.discount_percent == 50.0
        assert tier.discount_cap_vnd is None

    def test_cofund_larger_than_discount_is_flagged_not_hidden(self) -> None:
        """Grab does not fund more than the discount it funds.

        If that comes out of the parse, one of the two sentences was
        misread. Both numbers stay visible and the tier says so — a
        clamped or hidden figure would look correct.
        """
        detail = parse_event_detail(
            {
                "sections": [
                    _lever(
                        [
                            {
                                "title": "Giảm 1.000đ cho đơn hàng",
                                "bullets": [
                                    {"type": "CO_FUND", "content": "Grab đồng tài trợ 12.000đ"}
                                ],
                            }
                        ]
                    )
                ]
            }
        )
        (tier,) = detail.tiers
        assert tier.merchant_cost_vnd == -11_000
        assert tier.parse_note != ""
        # 12.000/1.000 would be "Grab 1200%", which renders in the green
        # "worth joining" tone and feeds the overview card's headline
        # share — the one place `parse_note` never reaches.
        assert tier.grab_funded_pct is None

    def test_cofund_stated_without_a_discount_stays_unknown(self) -> None:
        """No discount to divide by → no funding ratio, not 0% and not 100%."""
        detail = parse_event_detail(
            {
                "sections": [
                    _lever(
                        [
                            {
                                "title": "Ưu đãi đặc biệt",
                                "bullets": [
                                    {"type": "CO_FUND", "content": "Grab đồng tài trợ 1.000đ"}
                                ],
                            }
                        ]
                    )
                ]
            }
        )
        (tier,) = detail.tiers
        assert tier.grab_cofund_vnd == 1_000
        assert tier.discount_vnd is None
        assert tier.merchant_cost_vnd is None
        assert tier.grab_funded_pct is None

    def test_costs_and_schedule(self) -> None:
        detail = parse_event_detail(
            {
                "sections": [
                    _section(
                        "COST",
                        {
                            "items": [
                                {
                                    "title": "Phí quảng cáo",
                                    "eyebrow": "8%",
                                    "subItems": [{"content": "Tính trên doanh thu"}],
                                }
                            ]
                        },
                    ),
                    _section(
                        "MULTI_CONTENT_V2",
                        {
                            "items": [
                                {
                                    "eyebrow": "Thời gian",
                                    "content": "01/08 - 31/08",
                                    "tags": [{"value": "Ưu tiên hiển thị"}],
                                }
                            ]
                        },
                    ),
                ]
            }
        )
        (cost,) = detail.costs
        assert (cost.title, cost.fee, cost.notes) == (
            "Phí quảng cáo",
            "8%",
            ["Tính trên doanh thu"],
        )
        (sched,) = detail.schedule
        assert (sched.label, sched.content, sched.tags) == (
            "Thời gian",
            "01/08 - 31/08",
            ["Ưu tiên hiển thị"],
        )

    def test_ad_placements_are_not_promo_tiers(self) -> None:
        """`CAROUSEL_AD` / `SEARCH_AD` rows sit in the same section as the
        tiers but are a different thing.

        Live payload for #B0T1G100: the "Quảng cáo" group holds two ad
        placements restating the headline discount with no bullets, since
        an ad placement has no per-order co-funding split. Rendered as
        tiers they showed a "Grab ?%" badge over three blank figures —
        two cards that looked like missing data on every load.
        """
        detail = parse_event_detail(
            {
                "sections": [
                    _section(
                        "LEVER_ITEM_V2",
                        {
                            "isGrabCoFund": True,
                            "items": [
                                {
                                    "title": "Quảng cáo",
                                    "subItems": [
                                        {
                                            "type": "CAROUSEL_AD",
                                            "promo": {"title": "Giảm 12.000₫ cho đơn hàng"},
                                        },
                                        {
                                            "type": "SEARCH_AD",
                                            "promo": {
                                                "title": "Giảm 12.000₫ cho đơn hàng",
                                                "subtitle": "Đơn tối thiểu 40.000₫",
                                            },
                                        },
                                    ],
                                },
                                {
                                    "title": "Khuyến mại",
                                    "subItems": [
                                        {
                                            "type": "ORDER",
                                            "title": "Giảm 12.000₫ cho đơn hàng",
                                            "bullets": [
                                                {
                                                    "type": "CO_FUND",
                                                    "content": "Grab đồng tài trợ 1.000₫",
                                                }
                                            ],
                                        }
                                    ],
                                },
                            ],
                        },
                    )
                ]
            }
        )
        assert [t.title for t in detail.tiers] == ["Giảm 12.000₫ cho đơn hàng"]
        assert detail.tiers[0].kind == "ORDER"
        # Not discarded — moved somewhere they read as what they are.
        assert [a.kind for a in detail.ad_placements] == ["CAROUSEL_AD", "SEARCH_AD"]
        assert detail.ad_placements[1].subtitle == "Đơn tối thiểu 40.000₫"

    def test_unknown_ad_suffix_still_lands_in_placements(self) -> None:
        """Suffix match, not an allowlist.

        A placement type Grab adds later should not become a tier that
        appears to fund nothing.
        """
        detail = parse_event_detail(
            {
                "sections": [
                    _lever([{"type": "BANNER_AD", "promo": {"title": "Quảng cáo mới"}}])
                ]
            }
        )
        assert detail.tiers == []
        assert [a.kind for a in detail.ad_placements] == ["BANNER_AD"]

    def test_identical_tiers_collapse(self) -> None:
        """Grab sends the same row twice.

        Live: #B0T1G100 lists "Giảm 10.000₫ cho đơn hàng" twice with
        byte-identical bullets. Two rows the operator can't tell apart are
        one offer shown twice, and the repeat makes the program look like
        it has more options than it does.
        """
        row = {
            "type": "ORDER",
            "title": "Giảm 10.000₫ cho đơn hàng",
            "bullets": [
                {"type": "MOV", "content": "Giá trị đơn hàng tối thiểu 40.000₫"},
                {"type": "CO_FUND", "content": "Grab đồng tài trợ 2.000₫"},
            ],
        }
        detail = parse_event_detail({"sections": [_lever([dict(row), dict(row)])]})
        assert len(detail.tiers) == 1
        assert detail.tiers[0].grab_funded_pct == pytest.approx(0.2)

    def test_tiers_differing_in_any_term_are_both_kept(self) -> None:
        """Dedupe must not merge two genuinely different offers."""
        detail = parse_event_detail(
            {
                "sections": [
                    _lever(
                        [
                            {
                                "type": "ORDER",
                                "title": "Giảm 10.000₫ cho đơn hàng",
                                "bullets": [
                                    {"type": "CO_FUND", "content": "Grab đồng tài trợ 2.000₫"}
                                ],
                            },
                            {
                                "type": "ORDER",
                                "title": "Giảm 10.000₫ cho đơn hàng",
                                "bullets": [
                                    {"type": "CO_FUND", "content": "Grab đồng tài trợ 3.000₫"}
                                ],
                            },
                        ]
                    )
                ]
            }
        )
        assert len(detail.tiers) == 2

    def test_tiers_differing_only_in_subtitle_minimum_order_are_kept(self) -> None:
        """A term can arrive outside the bullets.

        When the minimum order comes from `promo.subtitle`, the bullets are
        empty — so a dedupe key built from bullets alone would merge two
        tiers with different minimum orders and delete a real offer.
        """
        detail = parse_event_detail(
            {
                "sections": [
                    _lever(
                        [
                            {
                                "type": "ORDER",
                                "promo": {
                                    "title": "Giảm 12.000₫ cho đơn hàng",
                                    "subtitle": "Đơn tối thiểu 40.000₫",
                                },
                            },
                            {
                                "type": "ORDER",
                                "promo": {
                                    "title": "Giảm 12.000₫ cho đơn hàng",
                                    "subtitle": "Đơn tối thiểu 100.000₫",
                                },
                            },
                        ]
                    )
                ]
            }
        )
        assert [t.min_order_vnd for t in detail.tiers] == [40_000, 100_000]

    def test_ad_kind_nested_under_promo(self) -> None:
        """Grab relocates fields between `sub` and `sub.promo`.

        The title already needs this fallback; an ad row whose type only
        appears under `promo` must not become a tier funding nothing.
        """
        detail = parse_event_detail(
            {
                "sections": [
                    _lever(
                        [{"promo": {"type": "SEARCH_AD", "title": "Quảng cáo tìm kiếm"}}]
                    )
                ]
            }
        )
        assert detail.tiers == []
        assert [a.kind for a in detail.ad_placements] == ["SEARCH_AD"]

    def test_cofund_flag_does_not_leak_between_lever_sections(self) -> None:
        """A second LEVER section that states nothing must stay unknown.

        A stale `False` carried over would stamp "Shop chịu 100%" on a
        tier that never claimed it.
        """
        detail = parse_event_detail(
            {
                "sections": [
                    _lever(
                        [{"type": "ITEM", "title": "Giảm 5.000₫ cho món"}],
                        isGrabCoFund=False,
                    ),
                    _lever([{"type": "ORDER", "title": "Giảm 12.000₫ cho đơn hàng"}]),
                ]
            }
        )
        first, second = detail.tiers
        assert first.grab_cofund_vnd == 0
        assert first.grab_funded_pct == 0.0
        assert second.grab_cofund_vnd is None
        assert second.grab_funded_pct is None

    def test_grab_stating_no_cofunding_means_zero_not_unknown(self) -> None:
        """`isGrabCoFund: false` → Grab 0%, shop pays all of it.

        Five of the six programs this store is offered say exactly that.
        Leaving them as "Grab ?%" with blank figures hid the single most
        important fact about them.
        """
        detail = parse_event_detail(
            {
                "sections": [
                    _lever(
                        [{"type": "ITEM", "title": "Giảm 15.000₫ cho một số món"}],
                        isGrabCoFund=False,
                    )
                ]
            }
        )
        (tier,) = detail.tiers
        assert tier.grab_cofund_vnd == 0
        assert tier.merchant_cost_vnd == 15_000
        assert tier.grab_funded_pct == 0.0

    def test_no_cofunding_on_a_percentage_tier_still_gives_a_known_split(self) -> None:
        """"Giảm 50%" has no đồng cost, but the split is still 0/100.

        The money stays None — it rides on the item price — while the
        ratio is knowable, which is what lets the card say "Shop chịu
        100%" instead of "—".
        """
        detail = parse_event_detail(
            {
                "sections": [
                    _lever(
                        [{"type": "ITEM", "title": "Giảm 50% cho một số món"}],
                        isGrabCoFund=False,
                    )
                ]
            }
        )
        (tier,) = detail.tiers
        assert tier.discount_percent == 50.0
        assert tier.merchant_cost_vnd is None
        assert tier.grab_funded_pct == 0.0

    def test_absent_cofund_flag_is_not_a_stated_zero(self) -> None:
        """An omitted `isGrabCoFund` must stay unknown.

        Now that False drives a definite "shop chịu 100%" on the card,
        coercing a missing key to False would put that claim on a program
        that never made it.
        """
        detail = parse_event_detail(
            {"sections": [_lever([{"type": "ORDER", "title": "Giảm 12.000₫ cho đơn hàng"}])]}
        )
        assert detail.is_grab_cofund is None
        (tier,) = detail.tiers
        assert tier.grab_cofund_vnd is None
        assert tier.grab_funded_pct is None

    def test_cofund_bullet_wins_over_the_program_flag(self) -> None:
        """A tier that states its own contribution keeps it."""
        detail = parse_event_detail(
            {
                "sections": [
                    _lever(
                        [
                            {
                                "type": "ORDER",
                                "title": "Giảm 12.000₫ cho đơn hàng",
                                "bullets": [
                                    {"type": "CO_FUND", "content": "Grab đồng tài trợ 1.000₫"}
                                ],
                            }
                        ],
                        isGrabCoFund=True,
                    )
                ]
            }
        )
        (tier,) = detail.tiers
        assert tier.grab_cofund_vnd == 1_000
        assert tier.merchant_cost_vnd == 11_000

    def test_minimum_order_read_from_promo_subtitle(self) -> None:
        """Some rows carry the MOV in `promo.subtitle`, not a bullet."""
        detail = parse_event_detail(
            {
                "sections": [
                    _lever(
                        [
                            {
                                "type": "ORDER",
                                "promo": {
                                    "title": "Giảm 12.000₫ cho đơn hàng",
                                    "subtitle": "Đơn tối thiểu 40.000₫",
                                },
                            }
                        ]
                    )
                ]
            }
        )
        (tier,) = detail.tiers
        assert tier.min_order_vnd == 40_000

    def test_join_signal_comes_from_the_footer_not_is_eligible(self) -> None:
        """`isEligible` in the detail payload is not the join signal.

        Verified against the live store: all six programs it is actively
        being offered come back `isEligible: false` from this endpoint,
        while the *list* endpoint says `true` and every one of them
        renders a working "Tham gia chiến dịch" button. Keying the UI off
        `isEligible` would tell the operator they can't join programs
        they can.
        """
        detail = parse_event_detail(
            {
                "isEligible": False,
                "sections": [
                    _section(
                        "EVENT_FOOTER",
                        {
                            "items": [
                                {
                                    "type": "OPT_IN",
                                    "cta": "Tham gia chiến dịch",
                                    "content": "Tôi đồng ý với [Điều khoản](https://grab.com/x)",
                                }
                            ]
                        },
                    )
                ],
            }
        )
        assert detail.is_eligible is False  # kept verbatim…
        assert detail.can_join is True  # …but this is what the UI reads
        assert detail.opt_in is not None
        assert detail.opt_in.cta == "Tham gia chiến dịch"

    def test_no_opt_in_means_cannot_join(self) -> None:
        detail = parse_event_detail(
            {"sections": [_section("EVENT_FOOTER", {"items": [{"type": "INFO"}]})]}
        )
        assert detail.can_join is False
        assert detail.opt_in is None

    def test_hero_image_prefers_assets_over_the_header_section(self) -> None:
        """`assets.hero` is the canonical banner; the section repeats it."""
        detail = parse_event_detail(
            {
                "assets": {"hero": {"type": "IMAGE", "path": "https://cdn/hero.webp"}},
                "sections": [
                    _section(
                        "EVENT_HEADER",
                        {"heroes": [{"path": "https://cdn/other.webp", "type": "IMAGE"}]},
                    )
                ],
            }
        )
        assert detail.hero_image_url == "https://cdn/hero.webp"

    def test_expired_signed_url_is_dropped(self) -> None:
        """Grab hands out signed URLs it never refreshes.

        Observed 2026-08-08: every image for "[Tiêu Điểm] Món ngon giá mềm
        giảm giá 5k" — list thumbnail, `assets.hero`, `assets.thumbnail`,
        header hero — carried `Expires=1785296064` (2026-07-29) and all
        four answered 403. Passing a URL we can prove is dead to the
        browser buys nothing but a broken-image icon.
        """
        dead = "https://cdn.cloudfront.net/a/hero.webp?Expires=1000000000&Signature=x"
        detail = parse_event_detail({"assets": {"hero": {"path": dead}}})
        assert detail.hero_image_url == ""
        assert find_image_url({"thumbnail": dead}) == ""

    def test_unexpired_signed_url_is_kept(self) -> None:
        alive = (
            "https://cdn.cloudfront.net/a/hero.webp?Expires=4102444800&Signature=x"
        )
        assert find_image_url({"thumbnail": alive}) == alive

    def test_unsigned_url_is_never_treated_as_expired(self) -> None:
        """Most of Grab's CDN paths are public — no `Expires` at all."""
        plain = "https://cdn.cloudfront.net/a/hero.webp?MD5=abc"
        assert find_image_url({"thumbnail": plain}) == plain

    def test_unreadable_expires_is_not_evidence_of_expiry(self) -> None:
        """A malformed timestamp should let the browser try.

        The frontend's error fallback catches it if it really is dead;
        discarding it here would blank an image that might work.
        """
        odd = "https://cdn.cloudfront.net/a/hero.webp?Expires=soon"
        assert find_image_url({"thumbnail": odd}) == odd

    def test_search_skips_a_dead_url_and_finds_a_live_one(self) -> None:
        """Expiry must not stop the walk at the first candidate."""
        payload = {
            "thumbnail": "https://cdn/a.webp?Expires=1000000000&Signature=x",
            "banner": "https://cdn/b.webp",
        }
        assert find_image_url(payload) == "https://cdn/b.webp"

    def test_a_dead_url_nested_deeper_is_also_skipped(self) -> None:
        payload = {
            "assets": {"hero": {"path": "https://cdn/a.webp?Expires=1000000000"}},
            "extra": {"banner": "https://cdn/b.webp"},
        }
        assert find_image_url(payload) == "https://cdn/b.webp"

    def test_real_extension_beats_a_hint_in_an_earlier_branch(self) -> None:
        """The preference has to hold across the whole tree, not per node.

        With one interleaved pass, an extensionless `meta.icon` won over a
        genuine `photos.thumb.jpg` purely for sitting in an earlier branch
        — a wrong image rather than a missing one.
        """
        payload = {
            "meta": {"icon": "https://cdn/a"},
            "photos": {"thumb": "https://cdn/b.jpg"},
        }
        assert find_image_url(payload) == "https://cdn/b.jpg"

    def test_hint_still_used_when_nothing_has_an_extension(self) -> None:
        """Many CDNs serve extensionless URLs — the fallback still matters."""
        payload = {"meta": {"icon": "https://cdn/a"}}
        assert find_image_url(payload) == "https://cdn/a"

    def test_a_second_live_expires_keeps_the_url(self) -> None:
        """Expired only when every stamp has passed.

        Taking just the first would throw away a working URL if Grab ever
        put a stale timestamp alongside a valid one.
        """
        url = "https://cdn/a.webp?Expires=1000000000&Expires=4102444800"
        assert find_image_url({"thumbnail": url}) == url

    def test_hero_image_is_upgraded_to_https(self) -> None:
        """Grab serves its CDN assets over plain http.

        A browser on an https dashboard blocks those as mixed content, so
        every banner would render blank in production while looking fine
        on localhost. The same paths answer 200 over https.
        """
        detail = parse_event_detail(
            {"assets": {"hero": {"path": "http://cdn.cloudfront.net/a/hero.webp"}}}
        )
        assert detail.hero_image_url == "https://cdn.cloudfront.net/a/hero.webp"

    def test_hero_image_falls_back_to_the_header_section(self) -> None:
        detail = parse_event_detail(
            {
                "sections": [
                    _section(
                        "EVENT_HEADER",
                        {
                            "content": "Mô tả chương trình",
                            "heroes": [{"path": "https://cdn/other.webp", "type": "IMAGE"}],
                        },
                    )
                ]
            }
        )
        assert detail.hero_image_url == "https://cdn/other.webp"
        assert detail.description == "Mô tả chương trình"

    def test_unrecognised_footer_action_is_reported(self) -> None:
        """If Grab renames the join action, say so.

        `can_join` would otherwise read False and the program would look
        closed for a reason nothing in the UI could explain.
        """
        detail = parse_event_detail(
            {
                "sections": [
                    _section("EVENT_FOOTER", {"items": [{"type": "OPT_IN_V2"}]})
                ]
            }
        )
        assert detail.can_join is False
        assert detail.unknown_sections == ["EVENT_FOOTER:OPT_IN_V2"]

    def test_missing_lever_section_leaves_cofund_unknown(self) -> None:
        """No LEVER_ITEM_V2 → "chưa rõ", not "Grab không tài trợ".

        Same failure the `is_eligible` → `can_join` change fixed: an
        absent section is not a stated negative.
        """
        detail = parse_event_detail({"sections": [_section("COST", {})]})
        assert detail.is_grab_cofund is None

        stated = parse_event_detail({"sections": [_lever([], isGrabCoFund=False)]})
        assert stated.is_grab_cofund is False

    def test_header_and_footer_are_not_reported_as_unknown(self) -> None:
        """Both appear on every live program; leaving them undecoded put a
        permanent "chưa đọc được" warning on every single card."""
        detail = parse_event_detail(
            {
                "sections": [
                    _section("EVENT_HEADER", {}),
                    _section("EVENT_FOOTER", {}),
                ]
            }
        )
        assert detail.unknown_sections == []

    def test_unhandled_section_is_reported_not_dropped(self) -> None:
        """Grab adds section types without notice.

        Silently ignoring one makes unread terms indistinguishable from
        absent terms — the program page would look complete while a
        condition went unshown.
        """
        detail = parse_event_detail(
            {"sections": [_section("SOMETHING_GRAB_ADDED_LATER", {})]}
        )
        assert detail.unknown_sections == ["SOMETHING_GRAB_ADDED_LATER"]

    def test_survives_a_malformed_payload(self) -> None:
        """One bad section must not blank the whole program.

        `params` that isn't valid JSON, a section that isn't a dict, a
        `sections` key that's missing entirely — none should raise.
        """
        detail = parse_event_detail(
            {
                "name": "Hỏng",
                "sections": [
                    {"uiType": "LEVER_ITEM_V2", "params": "{not json"},
                    "a string, not a section",
                    {"uiType": "COST"},  # no params at all
                ],
            }
        )
        assert detail.name == "Hỏng"
        assert detail.tiers == []

        assert parse_event_detail({}).tiers == []


class TestAttachFunding:
    """Filling the overview cards with each program's funding share.

    The list endpoint carries no economics, so "does Grab co-fund this?"
    costs one request per program. That fan-out sits inside a page load,
    which is why it is bounded — and why every failure mode has to leave
    the page renderable.
    """

    @staticmethod
    def _events(n: int) -> list[SpotlightEvent]:
        return [SpotlightEvent(event_id=f"E{i}", name=f"CT {i}") for i in range(n)]

    @pytest.mark.asyncio
    async def test_fills_cofunding_and_best_share(self, monkeypatch) -> None:
        async def _fake(client, event_id):  # noqa: ARG001
            return {
                "sections": [
                    _lever(
                        [
                            {
                                "type": "ORDER",
                                "title": "Giảm 12.000₫ cho đơn hàng",
                                "bullets": [
                                    {"type": "CO_FUND", "content": "Grab đồng tài trợ 1.000₫"}
                                ],
                            },
                            {
                                "type": "ORDER",
                                "title": "Giảm 10.000₫ cho đơn hàng",
                                "bullets": [
                                    {"type": "CO_FUND", "content": "Grab đồng tài trợ 2.000₫"}
                                ],
                            },
                        ],
                        isGrabCoFund=True,
                    )
                ]
            }

        monkeypatch.setattr("app.routers.marketing.get_event_detail", _fake)
        events = self._events(3)
        assert await _attach_funding(object(), events) is True
        for e in events:
            assert e.is_grab_cofund is True
            # Best tier, not the first: 2.000/10.000 beats 1.000/12.000.
            assert e.max_grab_funded_pct == pytest.approx(0.2)

    @pytest.mark.asyncio
    async def test_one_failure_does_not_sink_the_others(self, monkeypatch) -> None:
        """A dead lookup must leave its card unannotated, not blank the page."""
        request = httpx.Request("GET", "https://api.grab.com/x")

        async def _fake(client, event_id):  # noqa: ARG001
            if event_id == "E1":
                raise httpx.HTTPStatusError(
                    "boom",
                    request=request,
                    response=httpx.Response(500, request=request),
                )
            return {"sections": [_lever([], isGrabCoFund=False)]}

        monkeypatch.setattr("app.routers.marketing.get_event_detail", _fake)
        events = self._events(3)
        # Reported as incomplete so the router can warn.
        assert await _attach_funding(object(), events) is False
        assert events[0].is_grab_cofund is False
        assert events[1].is_grab_cofund is None  # the failed one — no guess
        assert events[2].is_grab_cofund is False

    @pytest.mark.asyncio
    async def test_slow_grab_does_not_hold_the_page(self, monkeypatch) -> None:
        """Past the budget, remaining lookups are abandoned, not awaited.

        Without a deadline a store with many programs would turn one slow
        Grab response into a page that never loads.
        """
        monkeypatch.setattr("app.routers.marketing._ENRICH_BUDGET_S", 0.05)
        monkeypatch.setattr("app.routers.marketing._ENRICH_CONCURRENCY", 1)

        async def _fake(client, event_id):  # noqa: ARG001
            await asyncio.sleep(5)
            return {}

        monkeypatch.setattr("app.routers.marketing.get_event_detail", _fake)
        events = self._events(4)

        loop = asyncio.get_running_loop()
        start = loop.time()
        assert await _attach_funding(object(), events) is False
        assert loop.time() - start < 2.0
        assert all(e.is_grab_cofund is None for e in events)

    @pytest.mark.asyncio
    async def test_no_events_is_a_no_op(self) -> None:
        assert await _attach_funding(object(), []) is True


class TestOutgoingLanguageHeader:
    """`accept-language: vi` has to reach Grab, not just be declared.

    Verified against the live store: `vi` returns "Giảm 12.000₫ cho đơn
    hàng"; both `vi-VN` and `vi_VN` — the latter being `GrabClient`'s own
    default — return "12.000₫ off order". The whole parser is written for
    the Vietnamese wording, so a regression here would empty every figure
    while the requests still returned 200.
    """

    @pytest.mark.asyncio
    async def test_marketing_calls_override_the_client_default(self) -> None:
        from grab.endpoints import marketing as ep

        seen: list[dict[str, str]] = []

        class _Res:
            status_code = 200

            def raise_for_status(self) -> None:
                pass

            def json(self):
                return {"events": [], "eventID": "x"}

        class _Client:
            async def get(self, path, params=None, headers=None):  # noqa: ARG002
                seen.append(dict(headers or {}))
                return _Res()

        client = _Client()
        await ep.list_spotlight_events(client)
        await ep.get_event_detail(client, "EVT1")
        await ep.list_campaigns(client)

        assert len(seen) == 3
        for headers in seen:
            assert headers.get("accept-language") == "vi"
        # The campaigns call must keep its version header alongside.
        assert seen[2].get("x-marketing-version") == "GrabMerchant Marketing 2.0"


# ── router: GET /api/marketing/events/{id} ──────────────────────────────────


@pytest.fixture(autouse=True)
def _configured_settings():
    """Fernet + session keys, needed before `get_grab_client` decrypts."""
    settings.token_encryption_key = settings.generate_fernet_key()
    settings.session_secret = settings.generate_session_secret()
    yield


@pytest.fixture
def logged_in_client(monkeypatch):
    """A TestClient with a signed cookie for a user who owns one store."""
    engine = create_engine(
        "sqlite://",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    encrypted = encrypt_token("fake-token-for-tests")
    with Session(engine) as s:
        owner = User(
            username="merchant@example.com",
            display_name="merchant",
            password_hash="x",
            is_active=True,
        )
        s.add(owner)
        s.commit()
        s.refresh(owner)
        s.add(
            Store(
                owner_user_id=owner.id,
                merchant_id="zeus_store:5-C6VKAT5GRK3CTT",
                name="Test Store",
                encrypted_auth_token=encrypted,
                encrypted_xray_token=encrypted,
                encrypted_display_token=encrypted,
            )
        )
        s.commit()
        owner_id = owner.id

    def _override():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = _override
    client = TestClient(app)
    client.cookies.set(
        COOKIE_NAME,
        SessionToken(user_id=owner_id, exp=int(time.time()) + 86400).to_signed(
            settings.session_secret
        ),
    )
    try:
        yield client
    finally:
        app.dependency_overrides.clear()


def _stub_detail(monkeypatch, payload_or_exc):
    async def _fake(client, event_id):  # noqa: ARG001
        if isinstance(payload_or_exc, Exception):
            raise payload_or_exc
        return payload_or_exc

    monkeypatch.setattr("app.routers.marketing.get_event_detail", _fake)


class TestProgramDetailRoute:
    def test_returns_parsed_economics(self, logged_in_client, monkeypatch):
        _stub_detail(
            monkeypatch,
            {
                "eventID": "EVT1",
                "name": "Thúc Đẩy Doanh Số Cơ Bản",
                "isEligible": True,
                "sections": [
                    _lever(
                        [
                            {
                                "title": "Giảm 12.000đ cho đơn hàng",
                                "bullets": [
                                    {"type": "MOV", "content": "Giá trị đơn hàng tối thiểu 40.000đ"},
                                    {"type": "CO_FUND", "content": "Grab đồng tài trợ 1.000đ"},
                                ],
                            }
                        ],
                        isGrabCoFund=True,
                    )
                ],
            },
        )

        resp = logged_in_client.get("/api/marketing/events/EVT1")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["event_id"] == "EVT1"
        (tier,) = body["tiers"]
        assert tier["merchant_cost_vnd"] == 11_000
        assert tier["grab_funded_pct"] == pytest.approx(1_000 / 12_000)

    def test_unknown_program_is_404_not_502(self, logged_in_client, monkeypatch):
        """A program that no longer exists is the operator's problem to see.

        Collapsing it into a generic 502 would read as "Grab is down" and
        send them to check the wrong thing.
        """
        request = httpx.Request("GET", "https://api.grab.com/x")
        _stub_detail(
            monkeypatch,
            httpx.HTTPStatusError(
                "not found",
                request=request,
                response=httpx.Response(404, request=request),
            ),
        )
        resp = logged_in_client.get("/api/marketing/events/GONE")
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "grab_event_detail_failed"

    def test_grab_rejection_is_502(self, logged_in_client, monkeypatch):
        request = httpx.Request("GET", "https://api.grab.com/x")
        _stub_detail(
            monkeypatch,
            httpx.HTTPStatusError(
                "denied",
                request=request,
                response=httpx.Response(403, request=request),
            ),
        )
        resp = logged_in_client.get("/api/marketing/events/EVT1")
        assert resp.status_code == 502
        assert resp.json()["detail"]["grab_status"] == 403

    def test_transport_failure_is_502(self, logged_in_client, monkeypatch):
        _stub_detail(monkeypatch, httpx.ConnectError("no route to host"))
        resp = logged_in_client.get("/api/marketing/events/EVT1")
        assert resp.status_code == 502
        assert resp.json()["detail"]["code"] == "grab_unreachable"

    def test_requires_auth(self, logged_in_client, monkeypatch):
        _stub_detail(monkeypatch, {"eventID": "EVT1"})
        logged_in_client.cookies.clear()
        resp = logged_in_client.get("/api/marketing/events/EVT1")
        assert resp.status_code == 401
