"""Marketing router — programs on offer + campaigns the store joined."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException

from app.deps import get_grab_client, require_user
from app.models import User
from app.schemas.marketing import (
    CAMPAIGN_STATUSES,
    CampaignPerformance,
    MarketingCampaign,
    MarketingCounts,
    MarketingOverviewResponse,
    SpotlightEvent,
    SpotlightEventDetail,
    find_image_url,
    parse_event_detail,
)
from grab.endpoints.marketing import (
    get_event_detail,
    list_campaigns,
    list_spotlight_events,
)

log = logging.getLogger("pulseorder.marketing")

router = APIRouter(prefix="/api/marketing", tags=["marketing"])


def _as_float(raw: Any) -> float:
    """Grab sends money as strings, sometimes as `3.64e+06`.

    `float()` handles scientific notation; the capture script's own
    `format_money` had to do the same. Returns 0.0 rather than raising —
    one unparseable figure should not blank a whole campaign row.
    """
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            return float(raw.strip())
        except ValueError:
            return 0.0
    return 0.0


def _parse_event(raw: dict[str, Any]) -> SpotlightEvent:
    return SpotlightEvent(
        event_id=str(raw.get("eventID") or raw.get("id") or ""),
        name=str(raw.get("name") or ""),
        description=str(raw.get("description") or ""),
        is_eligible=bool(raw.get("isEligible", False)),
        image_url=find_image_url(raw),
        raw=raw,
    )


def _parse_campaign(raw: dict[str, Any], status: str) -> MarketingCampaign:
    info = raw.get("info") if isinstance(raw.get("info"), dict) else {}
    perf = raw.get("performance") if isinstance(raw.get("performance"), dict) else {}

    spend = _as_float(perf.get("marketingSpend"))
    sales = _as_float(perf.get("assistedSales"))
    orders = int(_as_float(perf.get("assistedOrders")))
    roms = _as_float(perf.get("ssmRoms"))

    return MarketingCampaign(
        campaign_id=str(
            info.get("campaignID") or info.get("id") or raw.get("campaignID") or ""
        ),
        name=str(info.get("name") or "").strip(),
        campaign_type=str(
            info.get("campaignTypeName") or info.get("campaignType") or ""
        ),
        status=status,
        start_time=str(info.get("startTime") or ""),
        end_time=str(info.get("endTime") or ""),
        image_url=find_image_url(raw),
        performance=CampaignPerformance(
            marketing_spend=spend,
            assisted_sales=sales,
            assisted_orders=orders,
            roms=roms,
            # A campaign that hasn't run yet has no numbers. That is not
            # the same as one that ran and returned nothing, and the UI
            # renders them differently — blank vs "0 đơn".
            has_data=bool(perf) and (spend > 0 or orders > 0 or sales > 0),
        ),
        raw=raw,
    )


#: How many program-detail lookups may be in flight at once, and how long
#: the whole enrichment pass may take. The catalogue is small in practice
#: (six programs for the store this was built against) but nothing in the
#: API caps it, so both bounds are hard: past the deadline the overview
#: returns with whatever came back and the rest simply carry no funding
#: note. A slow Grab must not turn into a slow dashboard.
_ENRICH_CONCURRENCY = 6
_ENRICH_BUDGET_S = 12.0


async def _attach_funding(client, events: list[SpotlightEvent]) -> bool:
    """Fill in each program's co-funding share from its detail payload.

    The list endpoint carries no economics at all — name, description and
    eligibility, nothing else. Whether Grab funds 20% of a discount or
    none of it only exists behind one request per program, so seeing it at
    a glance on the cards means fetching them here.

    Returns True when every lookup succeeded. Failures are per-program and
    silent in the payload: an unenriched card shows no funding note, which
    is honest, where a default would claim Grab funds nothing.
    """
    if not events:
        return True

    sem = asyncio.Semaphore(_ENRICH_CONCURRENCY)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _ENRICH_BUDGET_S

    async def one(event: SpotlightEvent) -> bool:
        if not event.event_id:
            return True
        async with sem:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return False
            try:
                raw = await asyncio.wait_for(
                    get_event_detail(client, event.event_id), timeout=remaining
                )
            except (httpx.HTTPError, asyncio.TimeoutError) as exc:
                log.info(
                    "marketing: funding lookup failed for %s: %r",
                    event.event_id, exc,
                )
                return False
            detail = parse_event_detail(raw)
            event.is_grab_cofund = detail.is_grab_cofund
            shares = [
                t.grab_funded_pct
                for t in detail.tiers
                if t.grab_funded_pct is not None
            ]
            event.max_grab_funded_pct = max(shares) if shares else None
            return True

    results = await asyncio.gather(
        *(one(e) for e in events), return_exceptions=True
    )
    return all(r is True for r in results)


@router.get("", response_model=MarketingOverviewResponse)
@router.get("/", response_model=MarketingOverviewResponse)
async def get_marketing_overview(
    user: User = Depends(require_user),
    client=Depends(get_grab_client),
) -> MarketingOverviewResponse:
    """Programs the store can join, plus the campaigns it already runs.

    Two unrelated Grab services, fetched concurrently — the page shows
    both and serialising them would only make it slower.

    Failure is isolated per half. The catalogue going down should not
    hide the campaigns already running, and vice versa; whichever half
    survives still renders and the other reports itself in `warnings`.
    That matters more here than elsewhere because these endpoints are new
    to this codebase and unproven against a live store.
    """
    events_task = asyncio.create_task(list_spotlight_events(client))
    campaigns_task = asyncio.create_task(list_campaigns(client))

    warnings: list[str] = []

    events: list[SpotlightEvent] = []
    try:
        raw_events = await events_task
        events = [_parse_event(e) for e in raw_events]
    except httpx.HTTPStatusError as exc:
        log.warning(
            "marketing: spotlight/events rejected for user=%s: %s — %s",
            user.id, exc.response.status_code, (exc.response.text or "")[:200],
        )
        warnings.append(
            f"Không tải được danh sách chương trình (Grab trả {exc.response.status_code})."
        )
    except httpx.HTTPError as exc:
        log.warning("marketing: spotlight/events transport error: %r", exc)
        warnings.append("Không kết nối được tới Grab để lấy danh sách chương trình.")

    if events and not await _attach_funding(client, events):
        warnings.append(
            "Một số chương trình chưa lấy được mức Grab tài trợ — mở chi tiết "
            "để xem đầy đủ."
        )

    campaigns: list[MarketingCampaign] = []
    counts = MarketingCounts()
    try:
        payload = await campaigns_task
        for status in CAMPAIGN_STATUSES:
            bucket = payload.get(status)
            if not isinstance(bucket, list):
                continue
            for item in bucket:
                if isinstance(item, dict):
                    campaigns.append(_parse_campaign(item, status))
        raw_counts = payload.get("totalCount")
        if isinstance(raw_counts, dict):
            counts = MarketingCounts(
                in_review=int(_as_float(raw_counts.get("inReview"))),
                upcoming=int(_as_float(raw_counts.get("upcoming"))),
                ongoing=int(_as_float(raw_counts.get("ongoing"))),
                evergreen=int(_as_float(raw_counts.get("evergreen"))),
                paused=int(_as_float(raw_counts.get("paused"))),
                past=int(_as_float(raw_counts.get("past"))),
            )
            counts.total = (
                counts.in_review
                + counts.upcoming
                + counts.ongoing
                + counts.evergreen
                + counts.paused
                + counts.past
            )
    except httpx.HTTPStatusError as exc:
        log.warning(
            "marketing: campaigns rejected for user=%s: %s — %s",
            user.id, exc.response.status_code, (exc.response.text or "")[:200],
        )
        warnings.append(
            f"Không tải được chiến dịch đang tham gia (Grab trả {exc.response.status_code})."
        )
    except httpx.HTTPError as exc:
        log.warning("marketing: campaigns transport error: %r", exc)
        warnings.append("Không kết nối được tới Grab để lấy chiến dịch.")

    return MarketingOverviewResponse(
        events=events,
        campaigns=campaigns,
        counts=counts,
        warnings=warnings,
    )


@router.get("/events/{event_id}", response_model=SpotlightEventDetail)
async def get_program_detail(
    event_id: str,
    user: User = Depends(require_user),
    client=Depends(get_grab_client),
) -> SpotlightEventDetail:
    """Full terms for one program, including the figures that decide it.

    Fetched **on demand**, one program at a time, rather than folded into
    the overview. A store can be offered a dozen programs and each needs
    its own request; fanning all of them out while the page loads would
    put a dozen sequential Grab calls inside one HTTP response, and nginx
    cuts `/api` off at 60s. The operator opens one program at a time, so
    this loads one at a time.
    """
    try:
        raw = await get_event_detail(client, event_id)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        log.warning(
            "marketing: event detail %s rejected for user=%s: %s — %s",
            event_id, user.id, status, (exc.response.text or "")[:200],
        )
        raise HTTPException(
            status_code=404 if status == 404 else 502,
            detail={
                "code": "grab_event_detail_failed",
                "message": (
                    "Không tìm thấy chương trình này trên Grab."
                    if status == 404
                    else f"Grab từ chối yêu cầu chi tiết chương trình (HTTP {status})."
                ),
                "grab_status": status,
            },
        ) from exc
    except httpx.HTTPError as exc:
        log.warning("marketing: event detail %s transport error: %r", event_id, exc)
        raise HTTPException(
            status_code=502,
            detail={
                "code": "grab_unreachable",
                "message": "Không kết nối được tới Grab.",
            },
        ) from exc

    detail = parse_event_detail(raw)
    if detail.unknown_sections:
        # Not an error, but worth a trace: Grab adding a section type is
        # how terms start going unread.
        log.info(
            "marketing: event %s has unhandled sections %s",
            event_id, sorted(set(detail.unknown_sections)),
        )
    return detail
