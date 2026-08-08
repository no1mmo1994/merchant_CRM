"""Tạp Dề Vàng — reading tier requirements out of Grab's rendered UI.

The tier page is a layout tree, not data. Every requirement exists only
inside an `analytics.on_show` impression block, with the human wording in
sibling text leaves. That makes the parser the load-bearing piece: get a
threshold or its direction wrong and the dashboard tells the operator to
push a number the wrong way to keep their tier.

Three things these tests exist to hold down, each learned from the live
payload rather than assumed:

  * the goals service answers **one metric per call** — asking for nine
    returns one, and not even the first one asked for;
  * some metrics have no figure at all, and rendering those as 0 would
    read as a spotless record on metrics where lower is better;
  * `rating` / `rating_count` must come from the feedback overview, not
    from goals, which reports the current month against a lifetime
    requirement.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from app.schemas.tiers import (
    METRIC_TO_GOAL_KEY,
    apply_progress,
    parse_number,
    parse_threshold,
    parse_tier_landing,
    required_goal_keys,
)
from grab.endpoints.tiers import (
    get_feedback_overview,
    get_goal_progress,
    get_tier_landing,
)


# ── building payloads shaped like the live one ───────────────────────────────


def _metric_node(
    *,
    tier: str,
    metric: str,
    status: str,
    label: str,
    requirement: str,
    current_tier: str = "Basic",
    first_month: str = "false",
) -> dict[str, Any]:
    """One METRIC_SHOWN block, laid out the way Grab lays them out."""
    return {
        "type": "column",
        "analytics": {
            "on_show": {
                "event": "METRIC_SHOWN",
                "params": {
                    "IS_FIRST_MONTH": first_month,
                    "METRIC_NAME": metric,
                    "METRIC_STATUS": status,
                    "SELECTED_TIER": tier,
                    "TIER_NAME": current_tier,
                },
            }
        },
        "children": [
            {"type": "text", "data": label},
            {"type": "text", "data": requirement},
        ],
    }


def _landing(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    return {"sdui_body": {"type": "screen", "children": nodes}, "additional_data": {}}


LIVE_SHAPED = _landing(
    [
        _metric_node(tier="Cơ Bản", metric="total_order", status="ACHIEVED",
                     label="Số lượng đơn hàng", requirement="Đạt ít nhất 1"),
        _metric_node(tier="Cơ Bản", metric="cancellation", status="NOT_ACHIEVED",
                     label="Tỷ lệ đơn hàng có thể tránh bị huỷ",
                     requirement="Giữ dưới mức 20%"),
        _metric_node(tier="Bạc", metric="total_order", status="NOT_ACHIEVED",
                     label="Số lượng đơn hàng", requirement="Đạt ít nhất 50"),
        _metric_node(tier="Bạc", metric="rating", status="ACHIEVED",
                     label="Số sao đánh giá trung bình", requirement="Đạt ít nhất 4.2"),
        _metric_node(tier="Vàng", metric="rating_count", status="NOT_ACHIEVED",
                     label="Số lượt đánh giá", requirement="Đạt ít nhất 100"),
        _metric_node(tier="Vàng", metric="missing_or_wrong_items", status="ACHIEVED",
                     label="Thiếu món hoặc sai món", requirement="Giữ dưới 1"),
    ]
)


# ── threshold parsing ────────────────────────────────────────────────────────


class TestParseThreshold:
    @pytest.mark.parametrize(
        "text,value,direction,is_percent",
        [
            ("Đạt ít nhất 50", 50.0, "min", False),
            ("Đạt ít nhất 4.2", 4.2, "min", False),
            ("Đạt ít nhất 90%", 90.0, "min", True),
            ("Giữ dưới mức 20%", 20.0, "max", True),
            ("Giữ dưới mức 5%", 5.0, "max", True),
            ("Giữ dưới 1", 1.0, "max", False),
        ],
    )
    def test_reads_every_phrasing_the_live_page_uses(
        self, text: str, value: float, direction: str, is_percent: bool
    ) -> None:
        t = parse_threshold(text)
        assert t.value == value
        assert t.direction == direction
        assert t.is_percent is is_percent

    def test_direction_is_the_load_bearing_part(self) -> None:
        """"Đạt ít nhất" and "Giữ dưới" pull opposite ways.

        Swapping them would tell the operator to raise their cancellation
        rate to keep a tier.
        """
        assert parse_threshold("Đạt ít nhất 50").direction == "min"
        assert parse_threshold("Giữ dưới mức 50%").direction == "max"

    def test_unrecognised_wording_yields_no_threshold(self) -> None:
        """The sentence still shows; it just gets no progress bar.

        Inventing a direction would be worse than showing none.
        """
        t = parse_threshold("Hoàn thành khoá đào tạo")
        assert t.value is None
        assert t.direction == ""

    def test_empty_and_none_are_safe(self) -> None:
        assert parse_threshold("").value is None
        assert parse_threshold(None).value is None  # type: ignore[arg-type]

    def test_vietnamese_decimal_comma(self) -> None:
        assert parse_number("22,22") == pytest.approx(22.22)
        assert parse_number("4.5") == 4.5
        assert parse_number("khong co so") is None


# ── landing-page parsing ─────────────────────────────────────────────────────


class TestParseTierLanding:
    def test_builds_the_ladder_in_grab_order(self) -> None:
        status = parse_tier_landing(LIVE_SHAPED)
        assert [lv.name for lv in status.levels] == ["Cơ Bản", "Bạc", "Vàng"]

    def test_reads_label_and_requirement_positionally(self) -> None:
        status = parse_tier_landing(LIVE_SHAPED)
        basic = status.levels[0]
        first = basic.metrics[0]
        assert first.label == "Số lượng đơn hàng"
        assert first.requirement == "Đạt ít nhất 1"
        assert first.threshold.value == 1.0

    def test_grabs_own_verdict_is_kept_not_recomputed(self) -> None:
        """ACHIEVED comes from Grab and decides the tier.

        Recomputing it from `current` vs the parsed threshold would let a
        misparsed sentence overrule the actual grade.
        """
        status = parse_tier_landing(LIVE_SHAPED)
        basic = status.levels[0]
        assert [m.achieved for m in basic.metrics] == [True, False]
        assert basic.achieved_count == 1
        assert basic.total_count == 2

    def test_current_tier_is_mapped_to_the_vietnamese_rung(self) -> None:
        status = parse_tier_landing(LIVE_SHAPED)
        assert status.current_tier_raw == "Basic"
        assert status.current_tier == "Cơ Bản"
        assert [lv.is_current for lv in status.levels] == [True, False, False]

    def test_unmapped_tier_name_marks_nothing_current(self) -> None:
        """A tier Grab renames must not silently mark the wrong rung.

        `TIER_NAME` and `SELECTED_TIER` are in different languages with
        nothing in the payload linking them, so the mapping is the one
        inference here — and a miss has to fail visibly, not quietly.
        """
        payload = _landing([
            _metric_node(tier="Bạc", metric="total_order", status="ACHIEVED",
                         label="Số lượng đơn hàng", requirement="Đạt ít nhất 50",
                         current_tier="Platinum"),
        ])
        status = parse_tier_landing(payload)
        assert status.current_tier_raw == "Platinum"
        assert status.current_tier == "Platinum"  # falls back, not guessed
        assert all(not lv.is_current for lv in status.levels)

    def test_first_month_flag(self) -> None:
        payload = _landing([
            _metric_node(tier="Cơ Bản", metric="total_order", status="ACHIEVED",
                         label="Số lượng đơn hàng", requirement="Đạt ít nhất 1",
                         first_month="true"),
        ])
        assert parse_tier_landing(payload).is_first_month is True

    def test_survives_a_payload_with_no_metrics(self) -> None:
        assert parse_tier_landing({}).levels == []
        assert parse_tier_landing({"sdui_body": {}}).levels == []
        assert parse_tier_landing({"sdui_body": None}).levels == []

    def test_node_with_too_few_texts_leaves_wording_blank(self) -> None:
        """A layout we don't recognise must not put the wrong string in
        the requirement slot — that slot drives the threshold."""
        node = _metric_node(tier="Bạc", metric="total_order", status="ACHIEVED",
                            label="Số lượng đơn hàng", requirement="Đạt ít nhất 50")
        node["children"] = [{"type": "text", "data": "Chỉ một dòng"}]
        status = parse_tier_landing(_landing([node]))
        metric = status.levels[0].metrics[0]
        assert metric.label == "Chỉ một dòng"
        assert metric.requirement == ""
        assert metric.threshold.value is None

    def test_goal_keys_come_from_the_page_not_a_fixed_list(self) -> None:
        """Grab changing which metrics a tier uses changes what we fetch."""
        keys = required_goal_keys(parse_tier_landing(LIVE_SHAPED))
        assert keys == ["orders", "cancellations", "rating", "rating_count",
                        "missing_or_wrong_items"]
        # The SDUI names and the goals names genuinely differ.
        assert METRIC_TO_GOAL_KEY["total_order"] == "orders"
        assert METRIC_TO_GOAL_KEY["offline"] == "offline_hours"


# ── merging progress ─────────────────────────────────────────────────────────


class TestApronTitle:
    """The badge shown on the dashboard header."""

    def test_derived_from_the_tier(self) -> None:
        from app.schemas.tiers import apron_title

        assert apron_title("Cơ Bản") == "Tạp Dề Cơ Bản"
        assert apron_title("Bạc") == "Tạp Dề Bạc"
        assert apron_title("Vàng") == "Tạp Dề Vàng"

    def test_unknown_tier_gets_no_badge(self) -> None:
        """A tier Grab adds must not become "Tạp Dề Platinum".

        An unmapped `TIER_NAME` falls back to its raw English name, and
        pasting that into the pattern would invent a badge Grab has never
        used. The tier itself still shows; only the badge waits.
        """
        from app.schemas.tiers import apron_title

        assert apron_title("Platinum") == ""
        assert apron_title("Kim Cương") == ""

    def test_no_tier_means_no_title(self) -> None:
        """A title over a blank tier would claim a standing nothing backs.

        Grab's own scorecard `title` is "Chúc mừng 🎉" — a banner about
        profile completeness, not an apron rank — so there is nothing to
        fall back to.
        """
        from app.schemas.tiers import apron_title

        assert apron_title("") == ""
        assert apron_title("   ") == ""
        assert apron_title(None) == ""  # type: ignore[arg-type]

    def test_follows_a_promotion(self) -> None:
        """Derived every time, never stored — a new tier renames the badge."""
        from app.schemas.tiers import apron_title

        payload = _landing([
            _metric_node(tier="Vàng", metric="total_order", status="ACHIEVED",
                         label="Số lượng đơn hàng", requirement="Đạt ít nhất 100",
                         current_tier="Gold"),
        ])
        status = parse_tier_landing(payload)
        assert apron_title(status.current_tier) == "Tạp Dề Vàng"


class TestApplyProgress:
    def test_one_value_fills_the_same_metric_on_every_rung(self) -> None:
        status = parse_tier_landing(LIVE_SHAPED)
        apply_progress(status, goal_values={"orders": "7"}, rating=None, rating_count=None)
        basic_orders = status.levels[0].metrics[0]
        silver_orders = status.levels[1].metrics[0]
        assert basic_orders.current == 7.0
        assert silver_orders.current == 7.0
        # Same measurement, different bars: 7 clears "ít nhất 1", not 50.
        assert basic_orders.achieved is True
        assert silver_orders.achieved is False

    def test_metric_with_no_figure_stays_unknown(self) -> None:
        """Grab returns nothing for `missing_or_wrong_items`.

        A 0 there would render as "no missing items" — a spotless record
        invented out of absent data, on a metric where lower is better.
        """
        status = parse_tier_landing(LIVE_SHAPED)
        apply_progress(status, goal_values={}, rating=None, rating_count=None)
        gold = status.levels[2]
        missing = next(m for m in gold.metrics if m.metric == "missing_or_wrong_items")
        assert missing.current is None
        assert missing.current_display == ""

    def test_empty_string_from_grab_is_also_unknown(self) -> None:
        status = parse_tier_landing(LIVE_SHAPED)
        apply_progress(status, goal_values={"orders": ""}, rating=None, rating_count=None)
        assert status.levels[0].metrics[0].current is None

    def test_rating_comes_from_feedback_not_goals(self) -> None:
        """Goals reports the month; the tier is judged on the lifetime.

        Live: goals says `rating_count` 0 for this month while the store
        has 14 all-time, and Grab's own ACHIEVED flag for "ít nhất 10"
        only makes sense against 14.
        """
        status = parse_tier_landing(LIVE_SHAPED)
        apply_progress(
            status,
            goal_values={"rating": "4.2", "rating_count": "0"},
            rating=4.5,
            rating_count=14,
        )
        rating = next(m for m in status.levels[1].metrics if m.metric == "rating")
        count = next(m for m in status.levels[2].metrics if m.metric == "rating_count")
        assert rating.current == 4.5
        assert count.current == 14.0
        assert status.rating == 4.5
        assert status.rating_count == 14

    def test_missing_feedback_leaves_rating_unknown(self) -> None:
        status = parse_tier_landing(LIVE_SHAPED)
        apply_progress(status, goal_values={}, rating=None, rating_count=None)
        rating = next(m for m in status.levels[1].metrics if m.metric == "rating")
        assert rating.current is None

    def test_profile_score_fills_the_metric_goals_cannot(self) -> None:
        """`score_completion_score` has no figure in the goals service.

        It does exist — in the scorecard endpoint, on a 0–100 scale that
        matches the requirement wording ("Đạt ít nhất 90%"). Without it
        the ladder showed "Chưa rõ" on a metric Grab publishes.
        """
        payload = _landing([
            _metric_node(tier="Vàng", metric="score_completion_score",
                         status="ACHIEVED",
                         label="Điểm hoàn thiện thông tin cửa hàng",
                         requirement="Đạt ít nhất 90%"),
        ])
        status = parse_tier_landing(payload)
        apply_progress(status, goal_values={}, rating=None, rating_count=None,
                       profile_score=100.0)
        metric = status.levels[0].metrics[0]
        assert metric.current == 100.0
        assert metric.current_display == "100"

    def test_profile_score_of_zero_is_a_real_figure(self) -> None:
        """A brand-new store with an empty profile scores 0, not "unknown".

        Guarding with `if profile_score:` instead of `is not None` would
        hide a real 0 — the one value on this metric that most needs
        acting on.
        """
        payload = _landing([
            _metric_node(tier="Vàng", metric="score_completion_score",
                         status="NOT_ACHIEVED",
                         label="Điểm hoàn thiện thông tin cửa hàng",
                         requirement="Đạt ít nhất 90%"),
        ])
        status = parse_tier_landing(payload)
        apply_progress(status, goal_values={}, rating=None, rating_count=None,
                       profile_score=0.0)
        metric = status.levels[0].metrics[0]
        assert metric.current == 0.0
        assert metric.current_display == "0"

    def test_absent_profile_score_stays_unknown(self) -> None:
        payload = _landing([
            _metric_node(tier="Vàng", metric="score_completion_score",
                         status="ACHIEVED",
                         label="Điểm hoàn thiện thông tin cửa hàng",
                         requirement="Đạt ít nhất 90%"),
        ])
        status = parse_tier_landing(payload)
        apply_progress(status, goal_values={}, rating=None, rating_count=None,
                       profile_score=None)
        assert status.levels[0].metrics[0].current is None

    def test_percentage_current_is_read(self) -> None:
        status = parse_tier_landing(LIVE_SHAPED)
        apply_progress(status, goal_values={"cancellations": "22.22"},
                       rating=None, rating_count=None)
        cancel = status.levels[0].metrics[1]
        assert cancel.current == pytest.approx(22.22)
        assert cancel.threshold.direction == "max"


# ── the Grab calls ───────────────────────────────────────────────────────────


class TestGrabEndpoints:
    @respx.mock
    @pytest.mark.asyncio
    async def test_goals_is_called_one_metric_at_a_time(self, grab_client) -> None:
        """Batching is not an optimisation here, it's data loss.

        Verified live: nine keys in one call returned a single goal, and
        not the first one asked for. Each metric therefore gets its own
        request, and this pins that.
        """
        route = respx.post("https://api.grab.com/mex-app/troy/mqp/v1/goals").mock(
            return_value=httpx.Response(
                200, json={"goals": [{"goal_name": "orders", "current": "7"}]}
            )
        )
        async with grab_client as c:
            goal = await get_goal_progress(
                c, "orders", start_date="2026-08-01", end_date="2026-08-08"
            )
        assert goal["current"] == "7"
        body = json.loads(route.calls[0].request.content)
        assert body["goals"] == ["orders"]
        assert body["startDate"] == "2026-08-01"
        assert body["endDate"] == "2026-08-08"

    @respx.mock
    @pytest.mark.asyncio
    async def test_goal_with_no_figure_returns_empty(self, grab_client) -> None:
        respx.post("https://api.grab.com/mex-app/troy/mqp/v1/goals").mock(
            return_value=httpx.Response(200, json={"goals": []})
        )
        async with grab_client as c:
            assert await get_goal_progress(
                c, "missing_or_wrong_items",
                start_date="2026-08-01", end_date="2026-08-08",
            ) == {}

    @respx.mock
    @pytest.mark.asyncio
    async def test_feedback_overview_unwraps(self, grab_client) -> None:
        respx.get(
            url__startswith="https://api.grab.com/mex-app/troy/insights/v1/feedback-overview"
        ).mock(
            return_value=httpx.Response(
                200,
                json={"feedbackOverview": {"aggregatedRatingScore": 4.5,
                                           "ratingCount": 14}},
            )
        )
        async with grab_client as c:
            fb = await get_feedback_overview(c)
        assert fb["aggregatedRatingScore"] == 4.5
        assert fb["ratingCount"] == 14

    @respx.mock
    @pytest.mark.asyncio
    async def test_landing_sends_the_captured_layout_params(self, grab_client) -> None:
        """The requirements are read out of the rendered layout, so the
        params that shape it are not cosmetic."""
        route = respx.get(
            url__startswith="https://api.grab.com/mex-app/troy/sdui/v2/view/mqp_tier.landing_page"
        ).mock(return_value=httpx.Response(200, json=LIVE_SHAPED))
        async with grab_client as c:
            data = await get_tier_landing(c)
        assert "sdui_body" in data
        qs = route.calls[0].request.url.params
        assert qs["params.mqp_child_size"] == "0.6"
        assert qs["params.tap_interaction"] == "false"
