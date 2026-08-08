"""Finance / revenue router — surfaces the data behind the Tài chính page.

Mirrors ``donhang/getdoanhthu.py``. The Python script:

  1. POSTs ``/mex/finances/mobile/v4/transactions/summary`` with a
     ``{businessLine: "GF", limit: 10, currency: "VND", filters:
     {dateTime: {from, to, frequency: "custom"}}}`` payload.
  2. Recursively walks ``data.uiBreakdown`` collecting labels.
  3. Pulls ``data.salesBalance`` and ``data.earningsBalance``.

We do the same walk server-side and return a flat
``FinancialSummaryResponse`` so the dashboard renders KPI cards from a
map lookup, no recursion on the client.

Auth tokens are auto-rotated via ``get_grab_client`` (see
``app/deps.py``), so this router doesn't touch tokens.

-----
NOTE on response shape (vs ``donhang/getdoanhthu.py``):

The operator's script was hardcoded to a Vietnamese-label set
(``"Doanh thu"``, ``"Doanh thu ròng"``, …) which the real Grab response
does NOT return — the live wire payload uses *English* labels
(``"Net sales"``, ``"Deduction"``, ``"VAT amount"``, ``"PIT amount"``,
``"Net earnings"``, …).  Also, the script assumed every labelled item
was a ``dict`` with ``value.value`` nested three levels deep; the
real response carries values as either:

  * structured ``{type: "text", value: "2.320.000", style: ...,
    color: ...}`` payload, or
  * a flat locale string like ``"+2.320.000₫"`` (balances).

We still walk recursively — the structure of ``uiBreakdown`` matches
the script — but we map the *English* labels to the *Vietnamese* UI
labels here so the dashboard can keep using the same merchant-facing
wording the operator's CLI was already printing.  See ``_LABEL_MAP``.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from app.deps import get_session, get_grab_client, require_user
from app.models import OrderArchive, Store, User
from app.schemas.finance import (
    FinancialMetricGroup,
    FinancialMetricValue,
    FinancialSettlement,
    FinancialSummaryResponse,
    FinancialTransaction,
    SettlementsListResponse,
    SettlementsSummaryResponse,
    TransactionsListResponse,
)
from grab.endpoints.finance import (
    get_financial_summary,
    get_settlements_summary,
    list_settlements,
    list_transactions,
)

log = logging.getLogger("pulseorder.finance")

router = APIRouter(prefix="/api/finance", tags=["finance"])


# Order matters — the UI renders KPI cards in this order, and the
# merchant's mental model follows: gross revenue → net revenue →
# deductions → specific taxes → take-home. The keys here are the
# *English* labels Grab actually returns; the values are the
# *Vietnamese* labels the UI renders (matching the operator's original
# CLI output in ``donhang/getdoanhthu.py``).
_METRIC_ORDER: tuple[str, ...] = (
    "Doanh thu",
    "Doanh thu ròng",
    "Khấu trừ",
    "Thuế GTGT",
    "Thuế TNCN",
    "Thu nhập ròng",
)

# English label (from Grab wire) → Vietnamese label (rendered on UI).
# Multi-key labels (``Deduction``) are handled by stacking values into
# the same Vietnamese bucket so the operator still sees a single
# "Khấu trừ" KPI that includes both platform commission and marketing.
# Grab answers in whatever `accept-language` asks for. `donhang/
# getdoanhthu.py` matches the Vietnamese labels directly and works, so
# both sets are listed rather than assuming one — a store that gets the
# other language should not silently lose every metric.
_LABEL_MAP: dict[str, str] = {
    # English wire labels
    "Net sales": "Doanh thu",
    "Net earnings": "Doanh thu ròng",  # mirror the operator's "Doanh thu ròng" phrasing
    "Sales": "Doanh thu",
    "Deduction": "Khấu trừ",
    "VAT amount": "Thuế GTGT",
    "PIT amount": "Thuế TNCN",
    "Net income": "Thu nhập ròng",
    "Take home": "Thu nhập ròng",
    # Vietnamese wire labels — identity mappings, so they survive the
    # same path instead of being dropped as "unknown".
    "Doanh thu": "Doanh thu",
    "Doanh thu ròng": "Doanh thu ròng",
    "Khấu trừ": "Khấu trừ",
    "Thuế GTGT": "Thuế GTGT",
    "Thuế TNCN": "Thuế TNCN",
    "Thu nhập ròng": "Thu nhập ròng",
}


# Strip ``+``/``-``/thousands separators from a locale-formatted integer
# like ``"+2.320.000₫"`` or ``"-455.518"`` to its integer ``2320000``.
# Keeps the sign (negative amounts are deductions / taxes).
_NUM_RE = re.compile(r"[^\d\-]")


def _parse_locale_int(raw: Any) -> int | None:
    """Best-effort integer extraction from any of the formats Grab uses.

    Returns ``None`` on failure rather than 0 — the caller decides
    whether "no value" means "skip this row" or "report zero".
    """
    if isinstance(raw, (int, float)):
        return int(raw)
    if not isinstance(raw, str):
        return None
    cleaned = _NUM_RE.sub("", raw)
    if cleaned in ("", "-", "--"):
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None


def _extract_text_value(value_field: Any) -> tuple[str, int | None]:
    """Pull ``(display, integer)`` from a uiBreakdown ``value`` field.

    Grab has three shapes here:

      1. ``{"type": "text", "value": "2.320.000", ...}`` → display is
         the string, integer is the parsed `value`.
      2. ``{"type": "icon", ...}`` (chevron decoration only) → no
         amount; we return ``("", None)``.
      3. ``{"type": "text", "value": "+1.760.082₫", "style": ...}`` →
         display carries the literal ``₫``, integer already parseable.
    Anything else returns ``("", None)`` and the caller decides.
    """
    if not isinstance(value_field, dict):
        # Some leaves carry the amount as a raw string at `value`.
        if isinstance(value_field, str):
            v = _parse_locale_int(value_field)
            return (value_field, v)
        return ("", None)
    payload_value = value_field.get("value")
    if isinstance(payload_value, str):
        v = _parse_locale_int(payload_value)
        display = payload_value if payload_value else ""
        # Some entries carry the styled "₫" inside `value` while the
        # parent's display is just the number — we keep the parent
        # str as-is when the caller already has it.
        return (display, v)
    if isinstance(payload_value, (int, float)):
        return (str(payload_value), int(payload_value))
    return ("", None)


def _coerce_balance(raw: Any) -> tuple[str, int]:
    """Coerce Grab's top-level balance string into ``(display, value)``.

    Real shape: ``"+2.320.000₫"`` / ``"+1.676.922₫"``.  We accept also
    a dict form (legacy / future-proofing) but never raise.
    """
    if isinstance(raw, dict):
        # Legacy / speculative shape — ``{"value": …, "display": …}``.
        display, val = _extract_text_value(raw)
        return (display or (str(val) if val is not None else "0"), val or 0)
    if isinstance(raw, str):
        val = _parse_locale_int(raw)
        return (raw, val if val is not None else 0)
    return ("0 ₫", 0)


def _extract_currency_name(raw: Any) -> str:
    """Pick the human-readable currency code from the ``currency`` object.

    Real shape::

        {"name": "VND", "locale": "vi_VN", "symbol": "₫",
         "decimal_digits": 0, "custom_pattern": ""}

    We only need the name; fall back to ``VND`` for any other shape.
    """
    if isinstance(raw, dict):
        name = raw.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return "VND"


def _walk(
    node: Any,
    metrics: dict[str, list[tuple[str, int]]],
    parent: tuple[str, int] | None = None,
) -> None:
    """Collect every labelled amount in the uiBreakdown tree.

    Mirrors ``donhang/getdoanhthu.py``'s ``extract_financial_metrics``
    (walk every list, descend into every ``uiBreakdown``) but keeps
    Grab's own label for each amount, because one bucket routinely holds
    several distinct costs — a store's "Khấu trừ" is the platform
    commission AND the advertising fee, and "#1 / #2" tells the operator
    nothing.

    Unmapped labels are kept rather than discarded. The advertising fee
    arrives under a "Tiếp thị" accordion that no mapping covers, so the
    old ``if label in _LABEL_MAP`` gate threw it away.

    **The accordion double-count.** Grab repeats the same number on a
    parent row and its first child: ``Khấu trừ -502.641`` then
    ``Phí nền tảng -502.641`` underneath. Both are the same money. A
    child whose amount equals its parent's is therefore treated as the
    parent's *name* — it renames the row already recorded instead of
    adding a second one. That is what turns an anonymous "Khấu trừ #2"
    into "Phí quảng cáo" without double-counting it.
    """
    if not isinstance(node, list):
        return
    for item in node:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "")
        recorded: tuple[str, int] | None = None
        if label:
            target = _LABEL_MAP.get(label, label)
            # Two read paths: own `value`, then fall back to the first
            # child's. The real response puts a chevron `value` next to a
            # numbered child for most lines.
            display, val = _extract_text_value(item.get("value"))
            if val is None:
                children = item.get("uiBreakdown")
                if isinstance(children, list) and children:
                    _display2, val2 = _extract_text_value(children[0].get("value"))
                    if val2 is not None:
                        val = val2
            if val is not None:
                if parent is not None and parent[1] == val:
                    # Same money as the row above: this is that row's
                    # detail, not a new cost. Two ways it can refine it:
                    #
                    #  * the child names a KNOWN metric — then the child
                    #    decides which bucket the money belongs in, and
                    #    the parent was only a container. Grab nests the
                    #    ad spend as Tiếp thị > Khấu trừ > Phí quảng cáo;
                    #    without this the amount would file itself under
                    #    "Tiếp thị" and never reach the Khấu trừ total.
                    #  * otherwise it is just a better name for the row.
                    bucket = metrics.get(parent[0])
                    if bucket and bucket[-1][1] == val:
                        if target in _METRIC_ORDER and target != parent[0]:
                            bucket.pop()
                            if not bucket:
                                metrics.pop(parent[0], None)
                            moved = metrics.setdefault(target, [])
                            if not moved or moved[-1][1] != val:
                                moved.append((label, val))
                            recorded = (target, val)
                        else:
                            if bucket[-1][0] != label:
                                bucket[-1] = (label, val)
                            recorded = parent
                    else:
                        recorded = parent
                else:
                    bucket = metrics.setdefault(target, [])
                    if not bucket or bucket[-1][1] != val:
                        bucket.append((label, val))
                    recorded = (target, val)
        # Descend — sibling subtrees carry more matches (two ``Deduction``
        # accordions, one for commission and one for marketing).
        deeper = item.get("uiBreakdown")
        if isinstance(deeper, list):
            _walk(deeper, metrics, recorded if recorded is not None else parent)


def _project_metrics(
    metrics_map: dict[str, list[tuple[str, int]]],
    raw_breakdown: list[dict[str, Any]] | None,
) -> list[FinancialMetricGroup]:
    """Project the dict-of-lists into ordered ``FinancialMetricGroup`` rows.

    Values are signed integers (negative for deductions/taxes). Display
    keeps the sign explicit so the UI shows "+1.760.082 ₫" /
    "-455.518 ₫" the same way Grab's merchant app does.
    """
    out: list[FinancialMetricGroup] = []
    seen: set[str] = set()

    def _sign_display(v: int) -> str:
        # Mirror Grab's merchant-app convention: positive values show
        # a leading "+", negatives a leading "-". `₫` suffix always.
        return ("+" if v >= 0 else "-") + f"{abs(v):,}".replace(",", ".") + " ₫"

    for label in _METRIC_ORDER:
        values = metrics_map.get(label) or []
        if not values:
            continue
        seen.add(label)
        out.append(
            FinancialMetricGroup(
                label=label,
                values=[
                    FinancialMetricValue(
                        display=_sign_display(v), value_minor=v, name=name
                    )
                    for name, v in values
                ],
            )
        )
    # Append extras (Marketing, Net marketing fee, etc.) so nothing
    # Grab surfaced is silently dropped.
    for label in sorted(metrics_map.keys() - seen):
        out.append(
            FinancialMetricGroup(
                label=label,
                values=[
                    FinancialMetricValue(
                        display=_sign_display(v), value_minor=v, name=name
                    )
                    for name, v in metrics_map[label]
                ],
            )
        )
    return out


def _count_orders_in_range(
    session: Session,
    user_id: int,
    start_date: str,
    end_date: str,
) -> int:
    """Count orders archived locally for the operator within the date range.

    The 30s ``orders_poll`` cron writes every order it sees into
    ``OrderArchive`` with ``first_seen_at`` stamped at first-sight
    time. This count surfaces that local snapshot to the dashboard
    as the "Tổng đơn" KPI on the overview — paired with the
    money totals it makes the implicit average-order-value
    (``sales_balance / total_orders``) obvious without an extra
    metric.

    Args:
        session: SQLModel session bound to the app's engine.
        user_id: Currently authenticated operator's id. We scope
            the count to stores they own so two operators sharing
            one DB never see each other's volume.
        start_date: ISO-8601 ``YYYY-MM-DD`` inclusive lower bound.
        end_date: ISO-8601 ``YYYY-MM-DD`` inclusive upper bound
            (we extend by one day internally so the comparison
            matches ``end_date 23:59:59`` rather than ``00:00:00``).

    Returns:
        Count of ``OrderArchive`` rows whose ``first_seen_at`` falls
        inside ``[start_date 00:00:00, end_date+1day 00:00:00)``
        and whose ``store.owner_user_id == user_id``. Zero if the
        operator has no owned store (degrades gracefully instead
        of raising).
    """
    from datetime import datetime, timedelta
    from sqlmodel import func, select as _sel

    try:
        lo = datetime.fromisoformat(start_date)
        hi_exclusive = datetime.fromisoformat(end_date) + timedelta(days=1)
    except ValueError:
        # Bad date string — return 0 rather than 500. The router's
        # Pydantic ``pattern=`` already rejects malformed dates
        # before we get here; this is a belt-and-suspenders for
        # downstream regressions.
        return 0

    owned_store_ids = list(
        session.exec(
            _sel(Store.id).where(Store.owner_user_id == user_id)
        ).all()
    )
    if not owned_store_ids:
        return 0

    count = session.exec(
        _sel(func.count(OrderArchive.id)).where(
            OrderArchive.store_id.in_(owned_store_ids),
            OrderArchive.first_seen_at >= lo,
            OrderArchive.first_seen_at < hi_exclusive,
        )
    ).one()
    return int(count or 0)


def _grab_failure(exc: httpx.HTTPStatusError) -> HTTPException:
    """Translate a Grab HTTPStatusError into a structured 502.
    Mirrors the ``code``/``message``/``grab_status``/``grab_body``
    envelope used by ``items.py`` so the frontend can surface a single
    toast string. The Vietnamese copy here is short and stable so
    later translations stay in sync.
    """
    grab_status = exc.response.status_code
    grab_body = exc.response.text[:500]
    msg = "Grab đang gặp sự cố — không tải được báo cáo tài chính. Thử lại sau ít phút."
    if grab_status in (401, 403):
        msg = "Phiên đăng nhập Grab đã hết hạn — đăng nhập lại để tiếp tục."
    return HTTPException(
        status_code=502,
        detail={
            "code": "grab_finance_summary_unavailable",
            "message": msg,
            "grab_status": grab_status,
            "grab_body": grab_body,
        },
    )


@router.get("/summary", response_model=FinancialSummaryResponse)
async def get_summary(
    start_date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="YYYY-MM-DD"),
    end_date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="YYYY-MM-DD"),
    user: User = Depends(require_user),
    client=Depends(get_grab_client),
    session: Session = Depends(get_session),
) -> FinancialSummaryResponse:
    """Return the financial summary for ``[start_date, end_date]``.

    The endpoint accepts a date range as query params (matches the
    ``?from=&to=`` convention already in use elsewhere on the
    dashboard) and projects Grab's recursive ``uiBreakdown`` into a
    flat list of Vietnamese-labelled metric groups, plus the two
    top-level balances (``salesBalance`` / ``earningsBalance``).
    """
    if start_date > end_date:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_date_range",
                "message": "Ngày bắt đầu phải trước ngày kết thúc.",
            },
        )

    log.info(
        "finance_summary requested user=%s range=%s..%s",
        user.id, start_date, end_date,
    )

    try:
        raw = await get_financial_summary(client, start_date=start_date, end_date=end_date)
    except httpx.HTTPStatusError as exc:
        # Surface the rejected body so we can see why Grab refused
        # without poking into the network tab. The 502 envelope
        # already carries `grab_body` but we log it here too for the
        # case where the operator is reading uvicorn logs directly.
        log.warning(
            "finance_summary rejected user=%s status=%s body=%s",
            user.id, exc.response.status_code, exc.response.text[:500],
        )
        raise _grab_failure(exc) from exc
    except httpx.HTTPError as exc:
        log.warning("finance_summary transport error user=%s: %r", user.id, exc)
        raise HTTPException(
            status_code=502,
            detail={
                "code": "grab_finance_summary_unavailable",
                "message": "Mất kết nối tới Grab — không tải được báo cáo tài chính.",
                "grab_status": 0,
                "grab_body": "",
            },
        ) from exc

    data = raw.get("data") if isinstance(raw, dict) else None
    if not isinstance(data, dict):
        # Grab returned something weird — surface a warning but still
        # echo the range so the UI doesn't show "—".
        return FinancialSummaryResponse(
            date_range={"from": start_date, "to": end_date},
            currency="VND",
            warnings=["Grab không trả về khối dữ liệu `data` cho khoảng thời gian này."],
        )

    currency_name = _extract_currency_name(data.get("currency"))
    sales_display, sales_int = _coerce_balance(data.get("salesBalance"))
    earn_display, earn_int = _coerce_balance(data.get("earningsBalance"))

    metrics_map: dict[str, list[tuple[str, int]]] = {}
    raw_breakdown = data.get("uiBreakdown")
    _walk(raw_breakdown if isinstance(raw_breakdown, list) else [], metrics_map)
    metric_groups = _project_metrics(metrics_map, raw_breakdown)

    warnings: list[str] = []
    if not metric_groups and not (sales_int or earn_int):
        warnings.append("Chưa có dữ liệu doanh thu trong khoảng thời gian đã chọn.")

    # Count orders archived locally for the operator. We do this
    # AFTER the Grab fetch so a slow Grab response doesn't hold the
    # session open while we read it. The count is scoped to the
    # operator's owned store(s) so two operators sharing the DB
    # never see each other's volume. Failures here degrade to 0
    # rather than 500 — the dashboard shows "0 đơn" and the user
    # can refresh; a hard error would block the entire summary.
    total_orders = 0
    try:
        total_orders = _count_orders_in_range(
            session, user.id, start_date, end_date,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "finance_summary: total_orders count failed user=%s: %r",
            user.id, exc,
        )
        total_orders = 0

    return FinancialSummaryResponse(
        date_range={"from": start_date, "to": end_date},
        currency=currency_name,
        sales_balance=FinancialMetricValue(display=sales_display, value_minor=sales_int),
        earnings_balance=FinancialMetricValue(display=earn_display, value_minor=earn_int),
        total_orders=total_orders,
        metrics=metric_groups,
        ui_breakdown=raw_breakdown if isinstance(raw_breakdown, list) else None,
        warnings=warnings,
    )


# ─── "Giao dịch" tab ────────────────────────────────────────────────────────


# Map Grab's localized "type" labels (English) to the merchant-friendly
# Vietnamese strings the dashboard renders.  English keys stay the source
# of truth so we can add new ones without translation effort; if Grab
# ever sends an unknown type we fall back to the raw English string.
_TRANSACTION_TYPE_LABELS: dict[str, str] = {
    "Food delivery": "Giao hàng thức ăn",
    "Marketing": "Quảng cáo",
    "Ad spend": "Chi quảng cáo",
    "Refund": "Hoàn tiền",
    "Adjustment": "Điều chỉnh",
}


def _transaction_label(t: dict[str, Any]) -> dict[str, Any]:
    """Translate a raw Grab transaction row into the dashboard shape.

    The model uses snake_case field names (`amount_display`,
    `transaction_date`); Pydantic v2 picks them up via the alias config
    declared on ``FinancialTransaction``.

    We also attach a Vietnamese `type_label` so the React side can
    render without doing locale work itself. Kept separate from the
    canonical `type` field so a debug operator can still see what
    Grab actually sent.
    """
    raw_type = str(t.get("type") or "")
    return {
        **t,
        "currencyName": _extract_currency_name(t.get("currency")),
        "typeLabel": _TRANSACTION_TYPE_LABELS.get(raw_type, raw_type),
    }


def _settlement_label(s: dict[str, Any]) -> dict[str, Any]:
    """Translate a raw Grab settlement row into the dashboard shape.

    `type` from Grab is currently always ``"Transferred"`` (the only
    status the live API returns). We map it to the Vietnamese copy
    the merchant app uses ("Đã chuyển khoản") and also keep the raw
    value so future statuses (Pending, Failed, …) still surface.
    """
    raw_type = str(s.get("type") or "")
    status_label = {
        "Transferred": "Đã chuyển khoản",
        "Pending": "Đang xử lý",
        "Failed": "Thất bại",
    }.get(raw_type, raw_type)
    return {
        **s,
        "currencyName": _extract_currency_name(s.get("currency")),
        "statusLabel": status_label,
    }


@router.get("/transactions", response_model=TransactionsListResponse)
async def get_transactions(
    start_date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    limit: int = Query(50, ge=1, le=100),
    user: User = Depends(require_user),
    client=Depends(get_grab_client),
) -> TransactionsListResponse:
    """Return the per-transaction ledger for ``[start_date, end_date]``.

    Powers the "Giao dịch" tab. We do **not** short-circuit on empty
    results — Grab returns ``{"data": {"transactions": []}}`` for date
    ranges where the merchant was inactive, and the dashboard should
    still echo back the requested range so the operator knows the
    endpoint actually ran (vs. silently failing).
    """
    if start_date > end_date:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_date_range",
                    "message": "Ngày bắt đầu phải trước ngày kết thúc."},
        )
    log.info("finance_transactions user=%s range=%s..%s limit=%s", user.id, start_date, end_date, limit)
    try:
        raw = await list_transactions(client, start_date=start_date, end_date=end_date, limit=limit)
    except httpx.HTTPStatusError as exc:
        log.warning("finance_transactions rejected: %s %s", exc.response.status_code, exc.response.text[:200])
        raise _grab_failure(exc) from exc
    except httpx.HTTPError as exc:
        log.warning("finance_transactions transport error: %r", exc)
        raise HTTPException(
            status_code=502,
            detail={"code": "grab_finance_transactions_unavailable",
                    "message": "Mất kết nối tới Grab — không tải được lịch sử giao dịch.",
                    "grab_status": 0, "grab_body": ""},
        ) from exc

    data = raw.get("data") if isinstance(raw, dict) else None
    if not isinstance(data, dict):
        return TransactionsListResponse(
            date_range={"from": start_date, "to": end_date},
            currency="VND",
            warnings=["Grab không trả về khối dữ liệu `data` cho giao dịch."],
        )

    raw_rows = data.get("transactions") or []
    rows = [_transaction_label(r) for r in raw_rows if isinstance(r, dict)]
    currency_name = _extract_currency_name(
        rows[0].get("currency") if rows else data.get("currency")
    )
    return TransactionsListResponse(
        date_range={"from": start_date, "to": end_date},
        currency=currency_name,
        transactions=[FinancialTransaction(**r) for r in rows],
        has_more=bool(data.get("hasMore")),
        next_offset=int(data.get("nextOffset") or 0) if str(data.get("nextOffset") or "").isdigit() else 0,
        warnings=[],
    )


# ─── "Số tiền thu về" tab ──────────────────────────────────────────────────


@router.get("/settlements/summary", response_model=SettlementsSummaryResponse)
async def get_settlements_summary_endpoint(
    start_date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    user: User = Depends(require_user),
    client=Depends(get_grab_client),
) -> SettlementsSummaryResponse:
    """Return the "Số dư" / "Còn thiếu Grab" totals.

    Drives the two KPI tiles the merchant app shows above the payout
    list. We rename ``accountsPayableBalance`` → ``payable_to_merchant``
    because the original name reflects Grab's internal accounting
    perspective (Grab is the "accounts payable" party from Vietnam's
    ledger view) and confuses the operator.
    """
    if start_date > end_date:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_date_range",
                    "message": "Ngày bắt đầu phải trước ngày kết thúc."},
        )
    log.info("finance_settlements_summary user=%s range=%s..%s", user.id, start_date, end_date)
    try:
        raw = await get_settlements_summary(client, start_date=start_date, end_date=end_date)
    except httpx.HTTPStatusError as exc:
        log.warning("finance_settlements_summary rejected: %s %s", exc.response.status_code, exc.response.text[:200])
        raise _grab_failure(exc) from exc
    except httpx.HTTPError as exc:
        log.warning("finance_settlements_summary transport error: %r", exc)
        raise HTTPException(
            status_code=502,
            detail={"code": "grab_settlements_summary_unavailable",
                    "message": "Mất kết nối tới Grab — không tải được số dư thanh toán.",
                    "grab_status": 0, "grab_body": ""},
        ) from exc

    data = raw.get("data") if isinstance(raw, dict) else None
    if not isinstance(data, dict):
        return SettlementsSummaryResponse(
            date_range={"from": start_date, "to": end_date},
            currency="VND",
            warnings=["Grab không trả về khối dữ liệu `data` cho số dư thanh toán."],
        )

    return SettlementsSummaryResponse(
        date_range={"from": start_date, "to": end_date},
        currency=_extract_currency_name(data.get("currency")),
        payable_to_merchant=int(data.get("accountsPayableBalance") or 0),
        owed_to_grab=int(data.get("owedToGrab") or 0),
        warnings=[],
    )


@router.get("/settlements", response_model=SettlementsListResponse)
async def get_settlements(
    start_date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    limit: int = Query(50, ge=1, le=100),
    user: User = Depends(require_user),
    client=Depends(get_grab_client),
) -> SettlementsListResponse:
    """Return the settlement (payout) history + summary in one round-trip.

    The merchant mobile app shows the summary tiles ("Số dư" / "Còn
    thiếu Grab") above the per-row list, so we fan out two Grab calls
    in parallel and combine them into one response. If the summary
    call 5xxs but the list still works, we still return the list with
    a warning rather than failing the whole tab.
    """
    if start_date > end_date:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_date_range",
                    "message": "Ngày bắt đầu phải trước ngày kết thúc."},
        )
    log.info("finance_settlements user=%s range=%s..%s limit=%s", user.id, start_date, end_date, limit)

    import asyncio as _asyncio
    async def _safe_list():
        try:
            return await list_settlements(client, start_date=start_date, end_date=end_date, limit=limit)
        except httpx.HTTPError as e:
            log.warning("finance_settlements list error: %r", e)
            return None
    async def _safe_summary():
        try:
            return await get_settlements_summary(client, start_date=start_date, end_date=end_date)
        except httpx.HTTPError as e:
            log.warning("finance_settlements summary error: %r", e)
            return None

    list_raw, summary_raw = await _asyncio.gather(_safe_list(), _safe_summary())
    warnings: list[str] = []

    settlements: list[FinancialSettlement] = []
    has_more = False
    next_offset = 0
    currency_name = "VND"
    if isinstance(list_raw, dict):
        ldata = list_raw.get("data")
        if isinstance(ldata, dict):
            raw_rows = ldata.get("settlements") or []
            rows = [_settlement_label(r) for r in raw_rows if isinstance(r, dict)]
            settlements = [FinancialSettlement(**r) for r in rows]
            has_more = bool(ldata.get("hasMore"))
            next_offset = int(ldata.get("nextOffset") or 0) if str(ldata.get("nextOffset") or "").isdigit() else 0
            if rows:
                currency_name = _extract_currency_name(rows[0].get("currency"))
        else:
            warnings.append("Grab không trả về danh sách settlements.")
    else:
        warnings.append("Không tải được danh sách settlements từ Grab.")

    summary: SettlementsSummaryResponse | None = None
    if isinstance(summary_raw, dict):
        sdata = summary_raw.get("data")
        if isinstance(sdata, dict):
            summary = SettlementsSummaryResponse(
                date_range={"from": start_date, "to": end_date},
                currency=_extract_currency_name(sdata.get("currency")),
                payable_to_merchant=int(sdata.get("accountsPayableBalance") or 0),
                owed_to_grab=int(sdata.get("owedToGrab") or 0),
            )
            # If the list didn't yield a currency, fall back to the
            # summary's; the merchant app always uses VND so this is
            # mostly defensive.
            if currency_name == "VND":
                cn = _extract_currency_name(sdata.get("currency"))
                if cn:
                    currency_name = cn
    else:
        warnings.append("Không tải được tổng quan thanh toán từ Grab.")

    return SettlementsListResponse(
        date_range={"from": start_date, "to": end_date},
        currency=currency_name,
        summary=summary,
        settlements=settlements,
        has_more=has_more,
        next_offset=next_offset,
        warnings=warnings,
    )
