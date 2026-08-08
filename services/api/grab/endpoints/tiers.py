"""Tạp Dề Vàng — Grab's merchant quality tier programme (MQP).

Three services, captured in `marketing/tapdevang.py`:

* `sdui/v2/view/mqp_tier.landing_page` — the tier ladder and every
  requirement, as a server-driven UI tree
* `mqp/v1/goals` — where the store currently stands on one metric
* `insights/v1/feedback-overview` — rating and rating count

They have to be combined: the tier page states what each tier *requires*
but never what the store has, and the goals service knows what the store
has but measures it against a different target of its own.
"""

from __future__ import annotations

import logging
from typing import Any

from grab.client import GrabClient

log = logging.getLogger("pulseorder.grab.tiers")


async def get_tier_landing(client: GrabClient) -> dict[str, Any]:
    """GET the MQP tier page — the ladder, its rungs and their conditions.

    Returns `{sdui_body, additional_data}`. `sdui_body` is a rendered UI
    tree, not data: the tier requirements are only recoverable from
    `analytics.on_show` blocks scattered through it. See
    `app.schemas.tiers.parse_tier_landing`.

    The two query params come from the capture. `mqp_child_size` and
    `tap_interaction` shape the layout Grab renders, and since the
    requirements are read out of that layout they are not cosmetic.
    """
    res = await client.get(
        "/mex-app/troy/sdui/v2/view/mqp_tier.landing_page",
        params={
            "params.mqp_child_size": "0.6",
            "params.tap_interaction": "false",
        },
    )
    res.raise_for_status()
    data = res.json()
    return data if isinstance(data, dict) else {}


async def get_goal_progress(
    client: GrabClient,
    goal_key: str,
    *,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    """POST one metric's current value for the period. **One key per call.**

    The body takes `goals` as a list, which reads like a batch endpoint.
    It is not. Verified against the live store: sending nine keys returned
    a single goal — and not even the first one asked for, but `rating`,
    the seventh. Eight metrics would have silently come back empty and
    every one of them would have rendered as "no progress yet".

    So the capture's one-request-per-metric loop is a requirement, not an
    oversight. Callers should run these concurrently rather than batch
    them.

    Returns the first goal object, or `{}` when Grab has no figure for
    this metric — which happens for real: `missing_or_wrong_items` and
    `score_completion_score` both come back with no `current` at all.
    """
    res = await client.post(
        "/mex-app/troy/mqp/v1/goals",
        json={
            "startDate": start_date,
            "endDate": end_date,
            "goals": [goal_key],
        },
    )
    res.raise_for_status()
    data = res.json()
    if not isinstance(data, dict):
        return {}
    goals = data.get("goals")
    if isinstance(goals, list) and goals and isinstance(goals[0], dict):
        return goals[0]
    return {}


async def get_feedback_overview(client: GrabClient) -> dict[str, Any]:
    """GET the store's rating and how many ratings it has.

    Needed because the goals service is useless for these two: `rating`
    comes back with an empty `current`, and `rating_count` reports the
    current month (0) while the tier is judged on the lifetime figure
    (14). The tier page's own ACHIEVED/NOT_ACHIEVED flags line up with
    the lifetime numbers, which is what settles it.
    """
    res = await client.get(
        "/mex-app/troy/insights/v1/feedback-overview",
        params={"serviceType": "DELIVERY", "dataRangeID": "ALL_TIME"},
    )
    res.raise_for_status()
    data = res.json()
    if not isinstance(data, dict):
        return {}
    overview = data.get("feedbackOverview")
    return overview if isinstance(overview, dict) else {}
