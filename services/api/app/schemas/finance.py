"""Pydantic schemas for the finance / revenue dashboard endpoint.

The wire shape mirrors ``donhang/getdoanhthu.py``'s output (which walks
``data.uiBreakdown`` recursively) but projected server-side into a
flat map so the frontend doesn't have to redo the walk on every render.

Why server-side projection:
  * Grab's ``uiBreakdown`` is a deeply-nested tree where the same
    Vietnamese label can appear at any depth with the same semantic
    value. Surfacing it as ``metrics: {label: [values]}`` lets the UI
    render KPI cards directly from a map lookup.
  * Multiple instances of the same label (e.g. ``"Doanh thu"`` once
    for gross, once for the merchant-side breakdown) are preserved by
    using a *list* per label — the operator's script does the same.
  * The full raw tree is still attached under ``ui_breakdown`` so the
    UI can show a "Xem chi tiết" drill-down if a future feature wants
    every leaf.

Sibling endpoints ("Giao dịch" and "Số tiền thu về" tabs) share the
same date-range validation pattern and expose their results as flat
list responses so the React side can `map()` without recursion.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class FinancialSummaryRequest(BaseModel):
    """Date range for a financial summary query.

    Both fields are ``YYYY-MM-DD`` strings — the dashboard renders a
    HTML ``<input type="date">`` whose value is already in that format,
    so we accept the raw string instead of parsing into ``date``.
    Pydantic validates format here so a typo returns 422 instead of
    being forwarded to Grab as a 400.
    """

    start_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="YYYY-MM-DD")
    end_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="YYYY-MM-DD")


class FinancialMetricValue(BaseModel):
    """Single occurrence of a financial metric value.

    `display` is the raw string from Grab (e.g. ``"8.000.000 ₫"``).
    `value_minor` is the integer amount in *minor units* (e.g. VND
    subunits = full VND since VND has no decimal) so the frontend can
    format it without re-parsing locale strings.
    """

    display: str = Field(default="", description="Raw display string from Grab (locale-formatted).")
    value_minor: int = Field(default=0, description="Integer amount in minor currency units.")
    name: str = Field(
        default="",
        description=(
            "Grab's own label for this row, kept because several rows can "
            "land in one bucket. A store's 'Khấu trừ' is both the platform "
            "commission and the advertising fee; without this the UI could "
            "only render them as an anonymous '#1' and '#2'."
        ),
    )


class FinancialMetricGroup(BaseModel):
    """All instances of a single Vietnamese-labelled metric.

    Mirrors ``donhang/getdoanhthu.py``'s ``metrics.setdefault(label,
    []).append(val)`` — the same label can appear more than once in
    the breakdown (gross + net, VAT + PIT, etc.), and we keep every
    occurrence so the UI can show them separately.
    """

    label: str
    values: list[FinancialMetricValue] = Field(default_factory=list)


class FinancialSummaryResponse(BaseModel):
    """Top-level response for ``GET /api/finance/summary``.

    Field layout matches what the dashboard renders top-to-bottom:
      * `date_range` — echoed back so the UI can confirm what it asked for.
      * `sales_balance` / `earnings_balance` — the two top-level
        balances from ``data.salesBalance`` / ``data.earningsBalance``.
      * `metrics` — the recursive-walk output, ordered for stable
        rendering. Each entry holds one of the six canonical labels.
      * `ui_breakdown` — the raw tree, in case the UI wants to show
        a drill-down. Omitted when Grab returns no breakdown.
      * `warnings` — non-fatal issues (e.g. extraction returned no
        metrics so the UI can show "Chưa có dữ liệu").
    """

    date_range: dict[str, str]
    currency: str = "VND"
    sales_balance: FinancialMetricValue | None = None
    earnings_balance: FinancialMetricValue | None = None
    total_orders: int = 0
    """Count of orders archived locally in ``[start_date, end_date]``.

    Populated by the router from ``OrderArchive.first_seen_at`` for the
    operator's owned store(s). Lives at the top level (next to
    ``sales_balance``) because the dashboard renders it as a peer
    KPI ("Tổng đơn") on the same row as Doanh thu / Chiết khấu /
    Thu nhập ròng — pairing the money totals with a count makes the
    average-order-value implicit (sales / total_orders).
    """
    metrics: list[FinancialMetricGroup] = Field(default_factory=list)
    ui_breakdown: list[dict[str, Any]] | None = None
    warnings: list[str] = Field(default_factory=list)


# ─── Transactions ("Giao dịch") tab ──────────────────────────────────────────


class FinancialTransaction(BaseModel):
    """One row in the merchant's transaction history.

    Mirrors what ``GET /mex/finances/mobile/v4/transactions/list``
    returns. The field names are slightly verbose (`amountDisplay`,
    `transactionDate`) because that's what Grab sends — the alternative
    (renaming server-side) breaks the round-trip when someone copies a
    raw row into a debug session.

    `type` is a localized English label from Grab ("Food delivery",
    "Marketing", "Ad spend", …). The router doesn't translate it; the
    dashboard renders the English label verbatim because the merchant
    app does the same.
    """

    id: str = ""
    name: str = ""
    amount: int = 0
    amount_display: str = Field(default="", alias="amountDisplay")
    datetime: str = ""
    transaction_date: str = Field(default="", alias="transactionDate")
    display_date: str = Field(default="", alias="displayDate")
    type: str = ""
    type_label: str = Field(default="", alias="typeLabel")
    currency_name: str = Field(default="VND", alias="currencyName")

    # Pydantic v2 lets the model be built from the external Grab
    # shape (which uses ``amountDisplay`` / ``transactionDate`` /
    # ``displayDate`` — snake-camel mix) while exposing snake_case
    # to the dashboard.  ``populate_by_name`` keeps the alias
    # bidirectional.
    model_config = {"populate_by_name": True}


class TransactionsListResponse(BaseModel):
    """Response for ``GET /api/finance/transactions``.

    Echoes the date range back so the UI can confirm what it asked
    for, then dumps the raw rows. ``has_more`` lets the dashboard
    decide whether to show a "load more" paginator without parsing
    the cursor itself.
    """

    date_range: dict[str, str]
    currency: str = "VND"
    transactions: list[FinancialTransaction] = Field(default_factory=list)
    has_more: bool = False
    next_offset: int = 0
    warnings: list[str] = Field(default_factory=list)


# ─── Settlements ("Số tiền thu về") tab ───────────────────────────────────────


class FinancialSettlement(BaseModel):
    """One payout row from ``/settlements/list``.

    `transaction_date` is the merchant-facing string Grab sends
    ("04/08/2026 04:55AM"), while ``datetime`` is the machine ISO
    timestamp — the dashboard renders the display string and keeps
    the ISO version for sorting.

    `type` is "Transferred" today (the only status we've seen); the
    router maps it to "Đã chuyển khoản" so the badge matches the
    merchant mobile app copy. The model keeps the English wire label
    in `type_raw` for the unusual case where Grab adds another.
    """

    id: str = ""
    amount: int = 0
    amount_display: str = Field(default="", alias="amountDisplay")
    datetime: str = ""
    transaction_date: str = Field(default="", alias="transactionDate")
    display_date: str = Field(default="", alias="displayDate")
    type_raw: str = Field(default="", alias="type")
    status_label: str = Field(default="", alias="statusLabel")
    currency_name: str = Field(default="VND", alias="currencyName")

    model_config = {"populate_by_name": True}


class SettlementsSummaryResponse(BaseModel):
    """Top-line settlement totals for ``GET /api/finance/settlements/summary``.

    These two numbers drive the "Số dư" / "Còn thiếu Grab" tiles the
    merchant app shows above the payout list. We rename
    ``accountsPayableBalance`` → ``payable_to_merchant`` (amount
    Grab still owes the merchant) because the original name is from
    Grab's internal accounting perspective and confuses the operator.

    `owed_to_grab` is the inverse — amount the merchant owes Grab
    (refunds, clawbacks, ad-spend overshoot). Often 0.
    """

    date_range: dict[str, str]
    currency: str = "VND"
    payable_to_merchant: int = 0
    owed_to_grab: int = 0
    warnings: list[str] = Field(default_factory=list)


class SettlementsListResponse(BaseModel):
    """Response for ``GET /api/finance/settlements``.

    Returns the rows plus the summary totals in one envelope so the
    "Số tiền thu về" tab can populate from a single round-trip.  List
    order matches Grab's payout history (most recent first).
    """

    date_range: dict[str, str]
    currency: str = "VND"
    summary: SettlementsSummaryResponse | None = None
    settlements: list[FinancialSettlement] = Field(default_factory=list)
    has_more: bool = False
    next_offset: int = 0
    warnings: list[str] = Field(default_factory=list)
