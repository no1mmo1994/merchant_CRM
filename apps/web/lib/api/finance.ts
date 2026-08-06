import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

/**
 * Finance / revenue API surface.
 *
 * Mirrors services/api/app/routers/finance.py.
 *
 * GET /api/finance/summary?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD
 *   → FinancialSummaryResponse
 *
 * The wire shape comes from a server-side projection of Grab's
 * recursive `uiBreakdown` tree (see `app/routers/finance.py:_walk`).
 * The dashboard reads the flat `metrics[]` array directly; the raw
 * tree is still attached under `ui_breakdown` for future drill-down
 * features.
 */

/** Single occurrence of a financial metric value. */
export interface FinancialMetricValue {
  /** Raw display string from Grab (locale-formatted). */
  display: string;
  /** Integer amount in minor currency units (e.g. VND subunits). */
  value_minor: number;
}

/**
 * All instances of a single Vietnamese-labelled metric.
 *
 * Same label can appear more than once in Grab's breakdown (gross +
 * net, VAT + PIT, etc.) so we keep every occurrence rather than
 * collapsing to a single number.
 */
export interface FinancialMetricGroup {
  label: string;
  values: FinancialMetricValue[];
}

/**
 * Top-level response for `GET /api/finance/summary`.
 * Field layout matches what the dashboard renders top-to-bottom.
 */
export interface FinancialSummaryResponse {
  /** Echoed back so the UI can confirm what it asked for. */
  date_range: { from: string; to: string };
  /** Currency code (defaults to VND). */
  currency: string;
  sales_balance: FinancialMetricValue | null;
  earnings_balance: FinancialMetricValue | null;
  /** Recursive-walk output, ordered for stable rendering. */
  metrics: FinancialMetricGroup[];
  /** Raw `uiBreakdown` tree for drill-downs (omitted if empty). */
  ui_breakdown?: unknown[] | null;
  /** Non-fatal issues (e.g. "no data for range"). */
  warnings: string[];
}

const SUMMARY_KEY = ["finance", "summary"] as const;

interface SummaryQueryParams {
  start_date: string;
  end_date: string;
}

async function fetchSummary(params: SummaryQueryParams): Promise<FinancialSummaryResponse> {
  const qs = new URLSearchParams({
    start_date: params.start_date,
    end_date: params.end_date,
  }).toString();
  return api.get<FinancialSummaryResponse>(`/api/finance/summary?${qs}`);
}

/**
 * Pull the financial summary for `[start_date, end_date]`.
 *
 * Query is keyed by both dates so changing the range immediately
 * triggers a refetch and doesn't serve stale numbers from a previous
 * window. `staleTime: 60s` — short enough that re-opens feel fresh,
 * long enough that flipping pages doesn't re-fetch.
 */
export function useFinanceSummary(start_date: string, end_date: string) {
  return useQuery({
    queryKey: [...SUMMARY_KEY, start_date, end_date] as const,
    queryFn: () => fetchSummary({ start_date, end_date }),
    enabled: Boolean(start_date) && Boolean(end_date) && start_date <= end_date,
    staleTime: 60_000,
  });
}

// ─── Transactions ("Giao dịch") tab ──────────────────────────────────────────

/**
 * One row in the merchant's transaction ledger.
 *
 * `type_label` is the Vietnamese copy we surface (`Giao hàng thức ăn`,
 * `Quảng cáo`, …); the English wire label is kept in `type` so we can
 * pass unknown strings through to a "show original" affordance later.
 */
export interface FinancialTransaction {
  id: string;
  name: string;
  amount: number;
  amount_display: string;
  datetime: string;
  transaction_date: string;
  display_date: string;
  type: string;
  type_label: string;
  currency_name: string;
}

export interface TransactionsListResponse {
  date_range: { from: string; to: string };
  currency: string;
  transactions: FinancialTransaction[];
  has_more: boolean;
  next_offset: number;
  warnings: string[];
}

const TRANSACTIONS_KEY = ["finance", "transactions"] as const;

async function fetchTransactions(params: SummaryQueryParams): Promise<TransactionsListResponse> {
  const qs = new URLSearchParams({
    start_date: params.start_date,
    end_date: params.end_date,
  }).toString();
  return api.get<TransactionsListResponse>(`/api/finance/transactions?${qs}`);
}

/**
 * Pull the merchant's transaction history for `[start_date, end_date]`.
 *
 * Drives the "Giao dịch" tab. Same stale time as the summary so tab
 * switches share cache and don't pile up parallel requests.
 */
export function useFinanceTransactions(start_date: string, end_date: string) {
  return useQuery({
    queryKey: [...TRANSACTIONS_KEY, start_date, end_date] as const,
    queryFn: () => fetchTransactions({ start_date, end_date }),
    enabled: Boolean(start_date) && Boolean(end_date) && start_date <= end_date,
    staleTime: 60_000,
  });
}

// ─── Settlements ("Số tiền thu về") tab ───────────────────────────────────────

/**
 * One payout row from the merchant app's "Chi tiết thanh toán" list.
 *
 * `status_label` is the Vietnamese copy (`Đã chuyển khoản`,
 * `Đang xử lý`, `Thất bại`) — the router maps Grab's English
 * `type` (`Transferred` / `Pending` / `Failed`) to it.
 */
export interface FinancialSettlement {
  id: string;
  amount: number;
  amount_display: string;
  datetime: string;
  transaction_date: string;
  display_date: string;
  type_raw: string;
  status_label: string;
  currency_name: string;
}

export interface SettlementsSummaryResponse {
  date_range: { from: string; to: string };
  currency: string;
  /** Amount Grab still owes the merchant (the "Số dư" tile). */
  payable_to_merchant: number;
  /** Amount the merchant owes Grab (the "Còn thiếu Grab" tile). Often 0. */
  owed_to_grab: number;
  warnings: string[];
}

export interface SettlementsListResponse {
  date_range: { from: string; to: string };
  currency: string;
  summary: SettlementsSummaryResponse | null;
  settlements: FinancialSettlement[];
  has_more: boolean;
  next_offset: number;
  warnings: string[];
}

const SETTLEMENTS_KEY = ["finance", "settlements"] as const;

async function fetchSettlements(params: SummaryQueryParams): Promise<SettlementsListResponse> {
  const qs = new URLSearchParams({
    start_date: params.start_date,
    end_date: params.end_date,
  }).toString();
  return api.get<SettlementsListResponse>(`/api/finance/settlements?${qs}`);
}

/**
 * Pull the settlement list **and** its top-line summary for
 * `[start_date, end_date]`. Backend runs both in parallel, so a single
 * round-trip is enough for the "Số tiền thu về" tab.
 */
export function useFinanceSettlements(start_date: string, end_date: string) {
  return useQuery({
    queryKey: [...SETTLEMENTS_KEY, start_date, end_date] as const,
    queryFn: () => fetchSettlements({ start_date, end_date }),
    enabled: Boolean(start_date) && Boolean(end_date) && start_date <= end_date,
    staleTime: 60_000,
  });
}

export {
  SUMMARY_KEY,
  TRANSACTIONS_KEY,
  SETTLEMENTS_KEY,
};