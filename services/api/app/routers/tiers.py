"""Tạp Dề Vàng router — the tier ladder and how far the store is up it."""

from __future__ import annotations

import asyncio
import logging
from datetime import date

import httpx
from fastapi import APIRouter, Depends, HTTPException

from app.deps import get_grab_client, require_user
from app.models import User
from app.schemas.tiers import (
    FEEDBACK_BACKED_METRICS,
    PROFILE_BACKED_METRICS,
    GoldenApronStatus,
    GoldenApronSummary,
    apply_progress,
    apron_title,
    parse_tier_landing,
    required_goal_keys,
)
from grab.endpoints.store import get_scorecard
from grab.endpoints.tiers import (
    get_feedback_overview,
    get_goal_progress,
    get_tier_landing,
)

log = logging.getLogger("pulseorder.tiers")

router = APIRouter(prefix="/api/golden-apron", tags=["golden-apron"])

#: One request per metric — the goals service ignores all but one key per
#: call — so nine of them go out at once, bounded so a slow Grab can't
#: stack up connections, and capped in total so the page still answers.
_PROGRESS_CONCURRENCY = 5
_PROGRESS_BUDGET_S = 15.0


async def _collect_goal_values(
    client,
    keys: list[str],
    *,
    start_date: str,
    end_date: str,
) -> tuple[dict[str, str], list[str]]:
    """Fetch each metric's current value. Returns `(values, failed_keys)`.

    A metric that fails is simply absent from `values`, which reads
    downstream as "no figure" — the same as Grab having none. That is
    the honest reading either way, and it keeps one dead metric from
    blanking the whole ladder.
    """
    sem = asyncio.Semaphore(_PROGRESS_CONCURRENCY)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _PROGRESS_BUDGET_S

    async def one(key: str) -> str | None:
        async with sem:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return None
            try:
                goal = await asyncio.wait_for(
                    get_goal_progress(
                        client, key, start_date=start_date, end_date=end_date
                    ),
                    timeout=remaining,
                )
            except (httpx.HTTPError, asyncio.TimeoutError, ValueError) as exc:
                # `ValueError` covers `json.JSONDecodeError`: Grab can
                # answer 200 with an HTML gateway page, which is not an
                # `httpx.HTTPError` and would otherwise escape into the
                # gather below and be dropped without a log line — a
                # failed metric would then be indistinguishable from one
                # Grab genuinely has no figure for.
                log.info("golden-apron: goal %s failed: %r", key, exc)
                return None
            current = goal.get("current")
            return str(current) if current not in (None, "") else ""

    results = await asyncio.gather(*(one(k) for k in keys), return_exceptions=True)

    values: dict[str, str] = {}
    failed: list[str] = []
    # Paired with `keys` so an exception that still escapes is attributed
    # to the metric it came from rather than silently skipped.
    for key, result in zip(keys, results):
        if isinstance(result, BaseException):
            log.warning("golden-apron: goal %s raised unexpectedly: %r", key, result)
            failed.append(key)
        elif result is None:
            failed.append(key)
        elif result != "":
            values[key] = result
    return values, failed


async def _fetch_tier_landing(client, user_id: int) -> dict:
    """The tier page, or a 502 explaining which half of Grab said no."""
    try:
        return await get_tier_landing(client)
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        log.warning(
            "golden-apron: tier page rejected for user=%s: %s — %s",
            user_id, status_code, (exc.response.text or "")[:200],
        )
        raise HTTPException(
            status_code=502,
            detail={
                "code": "grab_tier_page_failed",
                "message": (
                    "Grab từ chối yêu cầu thông tin hạng "
                    f"(HTTP {status_code}). Token có thể đã hết hạn."
                ),
                "grab_status": status_code,
            },
        ) from exc
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("golden-apron: tier page unreadable: %r", exc)
        raise HTTPException(
            status_code=502,
            detail={
                "code": "grab_unreachable",
                "message": "Không kết nối được tới Grab.",
            },
        ) from exc


async def _profile_score(client) -> tuple[float | None, str]:
    """Store-profile completeness from the scorecard endpoint.

    Returns `(score, description)`. This is the only place the
    `score_completion_score` metric can be read: the goals service
    returns nothing for it at all.

    Grab's `score` is out of 100, not out of 5 — its `desc` is about
    having the information customers look for, and `shouldShowScore` is
    false. The dashboard used to render it as a star rating.
    """
    try:
        card = await get_scorecard(client)
    except (httpx.HTTPError, ValueError) as exc:
        log.info("golden-apron: scorecard failed: %r", exc)
        return None, ""
    if not isinstance(card, dict):
        return None, ""
    score = card.get("score")
    desc = card.get("desc")
    return (
        float(score) if isinstance(score, (int, float)) and not isinstance(score, bool) else None,
        str(desc or ""),
    )


async def _feedback_figures(client) -> tuple[float | None, int | None]:
    """Rating and rating count, both lifetime — see `get_feedback_overview`."""
    try:
        overview = await get_feedback_overview(client)
    except (httpx.HTTPError, ValueError) as exc:
        # `ValueError` for `json.JSONDecodeError`: Grab can answer 200
        # with an HTML gateway page, which is not an `httpx.HTTPError`.
        log.info("golden-apron: feedback overview failed: %r", exc)
        return None, None
    score = overview.get("aggregatedRatingScore")
    count = overview.get("ratingCount")
    return (
        float(score) if isinstance(score, (int, float)) else None,
        int(count) if isinstance(count, (int, float)) else None,
    )


@router.get("/summary", response_model=GoldenApronSummary)
async def get_golden_apron_summary(
    user: User = Depends(require_user),
    client=Depends(get_grab_client),
) -> GoldenApronSummary:
    """Tier, stars and apron title — what the dashboard header shows.

    Three concurrent reads, and deliberately none of the per-metric goals
    fan-out: the header renders a tier name and a star count, so making
    it wait on nine requests whose numbers it never shows would be paying
    for the whole ladder to draw one rung.
    """
    landing = await _fetch_tier_landing(client, user.id)
    status = parse_tier_landing(landing)

    # `return_exceptions` for the same reason as the full route: each
    # callee already handles Grab failing, so anything landing here is a
    # bug — and a bug in the profile lookup must not blank a header whose
    # tier is already known.
    feedback_result, profile_result = await asyncio.gather(
        _feedback_figures(client), _profile_score(client), return_exceptions=True
    )
    if isinstance(feedback_result, BaseException):
        log.warning("golden-apron: feedback raised unexpectedly: %r", feedback_result)
        rating, rating_count = None, None
    else:
        rating, rating_count = feedback_result
    if isinstance(profile_result, BaseException):
        log.warning("golden-apron: scorecard raised unexpectedly: %r", profile_result)
        profile_score, profile_desc = None, ""
    else:
        profile_score, profile_desc = profile_result

    summary = GoldenApronSummary(
        currentTier=status.current_tier,
        apronTitle=apron_title(status.current_tier),
        rating=rating,
        ratingCount=rating_count,
        profileScore=profile_score,
        profileDesc=profile_desc,
    )
    for level in status.levels:
        if level.is_current:
            summary.achieved_count = level.achieved_count
            summary.total_count = level.total_count
            break

    if not status.current_tier:
        summary.warnings.append("Grab chưa cho biết hạng hiện tại của cửa hàng.")
    if rating is None:
        summary.warnings.append("Chưa lấy được số sao đánh giá.")
    return summary


@router.get("", response_model=GoldenApronStatus)
@router.get("/", response_model=GoldenApronStatus)
async def get_golden_apron(
    user: User = Depends(require_user),
    client=Depends(get_grab_client),
) -> GoldenApronStatus:
    """The tier ladder, its conditions, and where the store stands.

    Three Grab services, in two rounds. The tier page comes first because
    it decides which metrics are worth asking about — fetching a fixed
    list instead would keep asking for metrics Grab has retired and miss
    any it adds.

    The tier page failing is fatal to the response: without it there are
    no rungs and no conditions, and a page of progress figures against
    nothing would be worse than an error. Everything after it degrades
    instead — a metric with no figure shows its condition and no number.
    """
    today = date.today()
    start_date = today.replace(day=1).isoformat()
    end_date = today.isoformat()

    landing = await _fetch_tier_landing(client, user.id)

    status = parse_tier_landing(landing)
    status.period_start = start_date
    status.period_end = end_date

    if not status.levels:
        log.warning("golden-apron: tier page carried no METRIC_SHOWN blocks")
        status.warnings.append(
            "Grab không trả về điều kiện hạng nào — giao diện của Grab có thể "
            "đã đổi."
        )
        return status

    # Only the metrics this store's ladder actually names.
    # Neither the feedback- nor the profile-backed metrics belong here:
    # the goals service has no answer for them, so asking would only
    # manufacture a failure against a metric already filled in elsewhere.
    _elsewhere = FEEDBACK_BACKED_METRICS | PROFILE_BACKED_METRICS
    goal_keys = [k for k in required_goal_keys(status) if k not in _elsewhere]

    goals_task = asyncio.create_task(
        _collect_goal_values(
            client, goal_keys, start_date=start_date, end_date=end_date
        )
    )
    # `return_exceptions` so no one leg can sink the others, or the ladder
    # itself. Each callee already handles Grab failing, so anything landing
    # here is a bug rather than an outage — logged loudly, page still drawn.
    feedback_result, profile_result, goals_result = await asyncio.gather(
        _feedback_figures(client),
        _profile_score(client),
        goals_task,
        return_exceptions=True,
    )

    if isinstance(feedback_result, BaseException):
        log.warning("golden-apron: feedback raised unexpectedly: %r", feedback_result)
        rating, rating_count = None, None
    else:
        rating, rating_count = feedback_result
    if rating is None:
        status.warnings.append("Chưa lấy được số sao và số lượt đánh giá từ Grab.")

    if isinstance(profile_result, BaseException):
        log.warning("golden-apron: scorecard raised unexpectedly: %r", profile_result)
        profile_score = None
    else:
        profile_score, _desc = profile_result

    if profile_score is None:
        status.warnings.append(
            "Chưa lấy được điểm hoàn thiện thông tin cửa hàng."
        )

    if isinstance(goals_result, BaseException):
        log.warning("golden-apron: goals raised unexpectedly: %r", goals_result)
        goal_values, failed = {}, list(goal_keys)
    else:
        goal_values, failed = goals_result

    apply_progress(
        status,
        goal_values=goal_values,
        rating=rating,
        rating_count=rating_count,
        profile_score=profile_score,
    )

    if failed:
        status.warnings.append(
            f"Chưa lấy được tiến độ của {len(failed)} chỉ số — điều kiện vẫn "
            "hiển thị, chỉ thiếu con số hiện tại."
        )

    return status
