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

from app.deps import get_grab_client, require_user
from app.models import User
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
_LABEL_MAP: dict[str, str] = {
    "Net sales": "Doanh thu",
    "Net earnings": "Doanh thu ròng",  # mirror the operator's "Doanh thu ròng" phrasing
    "Sales": "Doanh thu",
    "Deduction": "Khấu trừ",
    "VAT amount": "Thuế GTGT",
    "PIT amount": "Thuế TNCN",
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


def _walk(node: Any, metrics: dict[str, list[int]]) -> None:
    """Recursively collect ``_LABEL_MAP`` labels from the uiBreakdown tree.

    Mirrors the recursive structure of ``donhang/getdoanhthu.py``'s
    ``extract_financial_metrics`` (walk every list, descend into every
    ``uiBreakdown``), but uses *English* keys from ``_LABEL_MAP`` and
    the real ``_extract_text_value`` extractor rather than the script's
    Vietnamese set / nested-dict assumption. Each match is translated
    to its Vietnamese target before storage.

    Dedup: Grab's wire payload carries the same number on both a
    parent accordion (``Net sales`` on the ``Food & Dine Out`` row)
    and its first child (``Net sales`` on the indented subrow). The
    script handled this by reading only the first match it found; we
    do the same by deduping against the last-seen value per target
    label so we never display ``+2.680.000 ₫`` twice.
    """
    if not isinstance(node, list):
        return
    for item in node:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "")
        if label in _LABEL_MAP:
            target = _LABEL_MAP[label]
            # Two read paths: own `value`, then fall back to first
            # child's `value`. The script did the same fallback for
            # nested amounts; the real response places a chevron
            # `value` next to a numbered child for *most* lines.
            v = item.get("value")
            display, val = _extract_text_value(v)
            if val is None:
                children = item.get("uiBreakdown")
                if isinstance(children, list) and children:
                    display2, val2 = _extract_text_value(children[0].get("value"))
                    if val2 is not None:
                        display, val = display2 or display, val2
            if val is not None:
                bucket = metrics.setdefault(target, [])
                # Skip if this is the same value as the last recorded
                # one for this target — that's the accordion / first-
                # child double-tap pattern.
                if not bucket or bucket[-1] != val:
                    bucket.append(val)
        # Descend — sibling subtrees can carry more matches (e.g. two
        # ``Deduction`` accordions for "platform commission" and
        # "marketing").
        deeper = item.get("uiBreakdown")
        if isinstance(deeper, list):
            _walk(deeper, metrics)


def _project_metrics(
    metrics_map: dict[str, list[int]],
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
                    FinancialMetricValue(display=_sign_display(v), value_minor=v)
                    for v in values
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
                    FinancialMetricValue(display=_sign_display(v), value_minor=v)
                    for v in metrics_map[label]
                ],
            )
        )
    return out


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

    metrics_map: dict[str, list[int]] = {}
    raw_breakdown = data.get("uiBreakdown")
    _walk(raw_breakdown if isinstance(raw_breakdown, list) else [], metrics_map)
    metric_groups = _project_metrics(metrics_map, raw_breakdown)

    warnings: list[str] = []
    if not metric_groups and not (sales_int or earn_int):
        warnings.append("Chưa có dữ liệu doanh thu trong khoảng thời gian đã chọn.")

    return FinancialSummaryResponse(
        date_range={"from": start_date, "to": end_date},
        currency=currency_name,
        sales_balance=FinancialMetricValue(display=sales_display, value_minor=sales_int),
        earnings_balance=FinancialMetricValue(display=earn_display, value_minor=earn_int),
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
