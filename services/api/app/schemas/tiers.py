"""Schemas for Tạp Dề Vàng — reading tier requirements out of rendered UI.

`sdui/v2/view/mqp_tier.landing_page` returns a layout tree, not data. The
requirements exist only inside `analytics.on_show` blocks that the app
would fire as impression events:

    {"event": "METRIC_SHOWN",
     "params": {"SELECTED_TIER": "Bạc", "METRIC_NAME": "total_order",
                "METRIC_STATUS": "NOT_ACHIEVED", "TIER_NAME": "Basic"}}

with the human wording in sibling `type: "text"` nodes — first the metric
name ("Số lượng đơn hàng"), then its condition ("Đạt ít nhất 50").

So the thresholds have to be read out of Vietnamese prose, same as the
marketing programme terms. Every parsed number keeps the sentence it came
from, and the UI shows Grab's wording alongside.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

#: SDUI metric name → the key the goals service wants. Several differ:
#: the tier page says `total_order`, `offline`, `cancellation`; the goals
#: service wants `orders`, `offline_hours`, `cancellations`. Taken from
#: `marketing/tapdevang.py`, which is the only proof of the pairing.
METRIC_TO_GOAL_KEY: dict[str, str] = {
    "total_order": "orders",
    "order_delay": "order_delay",
    "offline": "offline_hours",
    "cancellation": "cancellations",
    "missing_or_wrong_items": "missing_or_wrong_items",
    "score_completion_score": "score_completion_score",
    "rating": "rating",
    "rating_count": "rating_count",
    "safety_incidents": "safety_incidents",
}

#: Metrics the goals service cannot answer, so their current value comes
#: from the feedback overview instead. Verified live: `rating` returns an
#: empty `current`, and `rating_count` returns this month's 0 while the
#: tier is judged on the lifetime 14.
FEEDBACK_BACKED_METRICS = {"rating", "rating_count"}

#: Metrics answered by the scorecard endpoint instead. The goals service
#: returns nothing at all for this one, so asking it would only produce a
#: failure that then gets counted against a metric already filled in.
PROFILE_BACKED_METRICS = {"score_completion_score"}

#: Grab's English tier names (`TIER_NAME`, which marks the store's
#: *current* tier) against the Vietnamese ones used for the rungs
#: (`SELECTED_TIER`). Nothing in the payload links them, so this is the
#: one inference here — and an unmatched name marks no tier current
#: rather than guessing.
TIER_NAME_VI: dict[str, str] = {
    "Basic": "Cơ Bản",
    "Silver": "Bạc",
    "Gold": "Vàng",
}

#: "Đạt ít nhất 4.2" / "Đạt ít nhất 50" — a floor: higher is better.
_AT_LEAST_RE = re.compile(r"ít\s*nhất\s*([\d.,]+)\s*(%?)", re.IGNORECASE)
#: "Giữ dưới mức 20%" / "Giữ dưới 1" — a ceiling: lower is better.
_BELOW_RE = re.compile(r"dưới\s*(?:mức\s*)?([\d.,]+)\s*(%?)", re.IGNORECASE)


def parse_number(text: str) -> float | None:
    """First number in a string, or None.

    `"4.2"` → 4.2, `"22,22"` → 22.22. Vietnamese writes decimals with a
    comma, and every figure Grab sends here is small enough that a dot is
    a decimal point too, never a thousands separator.
    """
    if not isinstance(text, str):
        return None
    m = re.search(r"[\d]+(?:[.,][\d]+)?", text)
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", "."))
    except ValueError:
        return None


class TierThreshold(BaseModel):
    """The number a requirement sentence is really asking for."""

    model_config = ConfigDict(populate_by_name=True)

    value: float | None = None
    #: `"min"` — the metric must reach this. `"max"` — it must stay under.
    #: Which way round decides whether progress means going up or down,
    #: and getting it backwards would tell the operator to do the opposite
    #: of what keeps their tier.
    direction: str = ""
    #: True when the figure is a percentage rather than a count.
    is_percent: bool = False


def parse_threshold(requirement: str) -> TierThreshold:
    """Read "Đạt ít nhất 50" / "Giữ dưới mức 20%" into a number and a sense.

    Returns an empty threshold when neither phrasing matches — the
    sentence is still shown, it just gets no progress bar. Inventing a
    direction would be worse than showing none.
    """
    text = requirement or ""
    m = _AT_LEAST_RE.search(text)
    if m:
        return TierThreshold(
            value=parse_number(m.group(1)),
            direction="min",
            is_percent=bool(m.group(2)),
        )
    m = _BELOW_RE.search(text)
    if m:
        return TierThreshold(
            value=parse_number(m.group(1)),
            direction="max",
            is_percent=bool(m.group(2)),
        )
    return TierThreshold()


class TierMetric(BaseModel):
    """One condition a tier places on the store."""

    model_config = ConfigDict(populate_by_name=True)

    #: Grab's machine name, e.g. `total_order`. Used to pair with goals.
    metric: str = ""
    #: Grab's wording, e.g. "Số lượng đơn hàng".
    label: str = ""
    #: Grab's wording for the condition, e.g. "Đạt ít nhất 50".
    requirement: str = ""
    threshold: TierThreshold = Field(default_factory=TierThreshold)
    #: Grab's own verdict for this store. Authoritative — it is what
    #: decides the tier, and it is not recomputed from `current`.
    achieved: bool = False
    #: Where the store stands. `None` when no service could say: Grab
    #: returns nothing at all for `missing_or_wrong_items` and
    #: `score_completion_score`. Rendering those as 0 would read as a
    #: perfect score on metrics where lower is better.
    current: float | None = None
    #: The same figure as Grab sent it, kept for display.
    current_display: str = Field(default="", alias="currentDisplay")


class TierLevel(BaseModel):
    """One rung of the ladder, with every condition it sets."""

    model_config = ConfigDict(populate_by_name=True)

    #: Vietnamese name as Grab labels the rung: "Cơ Bản", "Bạc", "Vàng".
    name: str = ""
    metrics: list[TierMetric] = Field(default_factory=list)
    #: True when this is the store's current tier. False on every rung
    #: when the current tier couldn't be matched — see `TIER_NAME_VI`.
    is_current: bool = Field(default=False, alias="isCurrent")
    achieved_count: int = Field(default=0, alias="achievedCount")
    total_count: int = Field(default=0, alias="totalCount")

    @property
    def is_fully_met(self) -> bool:
        return self.total_count > 0 and self.achieved_count == self.total_count


class GoldenApronStatus(BaseModel):
    """Everything the Tạp Dề Vàng page renders."""

    model_config = ConfigDict(populate_by_name=True)

    #: Grab's English name for the store's current tier, e.g. "Basic".
    current_tier_raw: str = Field(default="", alias="currentTierRaw")
    #: The Vietnamese name, or the raw one when unmapped.
    current_tier: str = Field(default="", alias="currentTier")
    #: True in the store's first month on the programme, when Grab
    #: applies different rules.
    is_first_month: bool = Field(default=False, alias="isFirstMonth")
    levels: list[TierLevel] = Field(default_factory=list)
    rating: float | None = None
    rating_count: int | None = Field(default=None, alias="ratingCount")
    #: Period the goals figures cover — Grab measures per calendar month.
    period_start: str = Field(default="", alias="periodStart")
    period_end: str = Field(default="", alias="periodEnd")
    warnings: list[str] = Field(default_factory=list)


def _metric_params(node: Any) -> dict[str, Any] | None:
    """The METRIC_SHOWN impression params on this node, if it has them."""
    if not isinstance(node, dict):
        return None
    analytics = node.get("analytics")
    on_show = analytics.get("on_show") if isinstance(analytics, dict) else None
    if not isinstance(on_show, dict) or on_show.get("event") != "METRIC_SHOWN":
        return None
    params = on_show.get("params")
    return params if isinstance(params, dict) else None


class GoldenApronSummary(BaseModel):
    """The three figures the dashboard's store header shows.

    A deliberately cheap sibling of the full ladder: it needs the tier
    page and two small reads, never the per-metric goals fan-out, so the
    dashboard doesn't pay for nine extra Grab round-trips it isn't going
    to render.
    """

    model_config = ConfigDict(populate_by_name=True)

    #: "Cơ Bản" / "Bạc" / "Vàng", empty when Grab didn't say.
    current_tier: str = Field(default="", alias="currentTier")
    #: The badge: "Tạp Dề Cơ Bản" and so on. Empty when the tier is
    #: unknown — a title invented over a blank tier would be a claim
    #: about the store's standing that nothing supports.
    apron_title: str = Field(default="", alias="apronTitle")
    rating: float | None = None
    rating_count: int | None = Field(default=None, alias="ratingCount")
    #: Progress on the tier the store currently holds.
    achieved_count: int = Field(default=0, alias="achievedCount")
    total_count: int = Field(default=0, alias="totalCount")
    #: Grab's store-profile completeness, 0–100. **Not** a star rating —
    #: the dashboard used to render it as "100.0 / 5".
    profile_score: float | None = Field(default=None, alias="profileScore")
    #: Grab's own sentence about that score.
    profile_desc: str = Field(default="", alias="profileDesc")
    warnings: list[str] = Field(default_factory=list)


def apron_title(tier: str) -> str:
    """"Cơ Bản" → "Tạp Dề Cơ Bản".

    Built from the tier rather than from Grab's scorecard `title`, which
    is a banner ("Chúc mừng 🎉") about profile completeness and says
    nothing about the apron.

    Only the three rungs Grab actually names get a badge. An unmapped
    tier falls back to its raw English name upstream, and pasting that
    into the pattern would produce "Tạp Dề Platinum" — a label Grab has
    never used, invented by this code. The tier itself still shows; the
    badge simply stays empty until we know what Grab calls it.
    """
    tier = (tier or "").strip()
    return f"Tạp Dề {tier}" if tier in set(TIER_NAME_VI.values()) else ""


def _iter_metric_nodes(node: Any):
    """Yield every `(params, texts)` pair from a METRIC_SHOWN block.

    `texts` is every `type: "text"` leaf belonging to that block, in
    document order. Grab puts the metric name first and its condition
    second, and the condition is what the threshold is read from.

    Collection stops at a nested METRIC_SHOWN. Grab's tree happens to be
    flat today, but if it ever embedded one metric card inside another
    — a "compare with the next tier" row, say — an outer card with fewer
    than two text leaves of its own would reach into the inner one and
    take its requirement as its own. That misassignment is invisible:
    both sentences are plausible, and the wrong threshold would simply
    render as fact.
    """
    if isinstance(node, dict):
        params = _metric_params(node)
        if params is not None:
            texts: list[str] = []

            def gather(n: Any, *, root: bool = False) -> None:
                if isinstance(n, dict):
                    if not root and _metric_params(n) is not None:
                        return
                    if n.get("type") == "text" and isinstance(n.get("data"), str):
                        texts.append(n["data"])
                    for v in n.values():
                        gather(v)
                elif isinstance(n, list):
                    for item in n:
                        gather(item)

            gather(node, root=True)
            yield params, texts
        for v in node.values():
            yield from _iter_metric_nodes(v)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_metric_nodes(item)


def parse_tier_landing(raw: dict[str, Any]) -> GoldenApronStatus:
    """Turn the rendered tier page into the ladder and its conditions.

    Rungs come out in the order Grab lays them out, which is the order
    they are climbed.
    """
    status = GoldenApronStatus()
    body = raw.get("sdui_body") if isinstance(raw, dict) else None
    if not isinstance(body, (dict, list)):
        return status

    levels: dict[str, TierLevel] = {}
    for params, texts in _iter_metric_nodes(body):
        tier_name = str(params.get("SELECTED_TIER") or "").strip()
        if not tier_name:
            continue

        if not status.current_tier_raw:
            status.current_tier_raw = str(params.get("TIER_NAME") or "")
            status.is_first_month = str(params.get("IS_FIRST_MONTH") or "").lower() == "true"

        level = levels.get(tier_name)
        if level is None:
            level = TierLevel(name=tier_name)
            levels[tier_name] = level

        metric = str(params.get("METRIC_NAME") or "")
        # Positional, because that is how Grab lays it out and there is no
        # key to go by. A node with fewer than two text leaves is a layout
        # we don't recognise, so its wording is left blank rather than
        # having the wrong string put in the requirement slot.
        label = texts[0] if len(texts) > 0 else ""
        requirement = texts[1] if len(texts) > 1 else ""

        level.metrics.append(
            TierMetric(
                metric=metric,
                label=label,
                requirement=requirement,
                threshold=parse_threshold(requirement),
                achieved=str(params.get("METRIC_STATUS") or "") == "ACHIEVED",
            )
        )

    for level in levels.values():
        level.total_count = len(level.metrics)
        level.achieved_count = sum(1 for m in level.metrics if m.achieved)

    status.levels = list(levels.values())

    if status.current_tier_raw:
        status.current_tier = TIER_NAME_VI.get(
            status.current_tier_raw, status.current_tier_raw
        )
        for level in status.levels:
            if level.name == status.current_tier:
                level.is_current = True

    return status


def required_goal_keys(status: GoldenApronStatus) -> list[str]:
    """Which goals to fetch — derived from the page, not hardcoded.

    Grab changing the metrics a tier is judged on then changes what gets
    fetched, instead of leaving a stale list quietly asking for retired
    metrics and missing new ones.
    """
    seen: list[str] = []
    for level in status.levels:
        for metric in level.metrics:
            key = METRIC_TO_GOAL_KEY.get(metric.metric)
            if key and key not in seen:
                seen.append(key)
    return seen


def apply_progress(
    status: GoldenApronStatus,
    *,
    goal_values: dict[str, str],
    rating: float | None,
    rating_count: int | None,
    profile_score: float | None = None,
) -> None:
    """Fill each metric's current value in place.

    Every rung is judged on the same measurements, so one value fills the
    same metric across all of them.

    `rating` and `rating_count` deliberately override anything the goals
    service said: it reports the current month while the tier is judged
    on the lifetime figure, and the page's own ACHIEVED flags match the
    lifetime numbers.
    """
    status.rating = rating
    status.rating_count = rating_count

    for level in status.levels:
        for metric in level.metrics:
            if metric.metric == "rating" and rating is not None:
                metric.current = rating
                metric.current_display = f"{rating:g}"
                continue
            if metric.metric == "rating_count" and rating_count is not None:
                metric.current = float(rating_count)
                metric.current_display = str(rating_count)
                continue
            if metric.metric == "score_completion_score" and profile_score is not None:
                # The goals service returns nothing at all for this one,
                # so the ladder showed "chưa rõ" on a metric Grab does
                # publish — just from the scorecard endpoint instead. Its
                # 0–100 scale lines up with the requirement wording
                # ("Đạt ít nhất 50%"), and the ACHIEVED flags agree.
                metric.current = profile_score
                metric.current_display = f"{profile_score:g}"
                continue

            key = METRIC_TO_GOAL_KEY.get(metric.metric)
            raw = goal_values.get(key or "", "")
            if raw == "" or raw is None:
                # Left as None on purpose. Grab genuinely returns nothing
                # for some metrics, and a 0 on "Thiếu món hoặc sai món"
                # would read as a clean record rather than as no data.
                continue
            metric.current_display = str(raw)
            metric.current = parse_number(str(raw))
