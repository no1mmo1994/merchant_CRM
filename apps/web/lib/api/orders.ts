import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

/**
 * Orders / customer-overview API surface.
 *
 * Mirrors services/api/app/routers/orders.py + grab/endpoints/orders.py
 * (which in turn mirror `donhang/getdonhangmoi.py` + `donhanghoantat_dondalamxong.py`).
 *
 * Endpoints:
 *   GET /api/orders               → OrderListResponse (preparing queue)
 *   GET /api/orders/{order_id}    → OrderDetail
 *   GET /api/orders/history       → OrderHistoryResponse (4 buckets)
 *   GET /api/orders/poll-status   → OrderPollStatus (2-min cron snapshot)
 *
 * All currency / price fields are strings (`"305.000"`, `"65.000"`)
 * because Grab sends them locale-formatted; we keep them as-is and
 * only parse to integer for the badge counters.
 *
 * ── Wire shape ───────────────────────────────────────────────────────────────
 *
 * IMPORTANT: every field below uses the **camelCase** name Grab
 * actually sends, NOT snake_case. FastAPI's `response_model` serializer
 * always emits the Pydantic alias when one is declared (the schemas
 * declare `alias="displayID"` / `alias="itemInfo"` / etc.). Confirmed
 * by probing `/api/orders/history` end-to-end — the response is
 * `{"displayID": "...", "itemInfo": {...}}`, not snake_case. Earlier
 * frontend code assumed snake_case and silently rendered `undefined`
 * everywhere — the "không hiển thị số tiền + mã đơn + sản phẩm" bug.
 *
 * The single snake_case surface left in this file is the URL query
 * string for `/api/orders/history` (`from_date` / `to_date` map to
 * FastAPI `Query(..., alias=…)` parameters in the router) — that one
 * stays snake_case because that's the documented API contract.
 */

export interface OrderEater {
  /** Wire key `ID` (aliased from `id`). */
  ID: string;
  name: string;
  /** Wire key `mobileNumber`. */
  mobileNumber: string;
  address: string;
  comment: string;
}

export interface OrderItemModifier {
  /** Wire key `modifierID`. */
  modifierID: string;
  /** Wire key `modifierName`. */
  modifierName: string;
  quantity: number;
  /** Wire key `priceDisplay`. */
  priceDisplay: string;
}

export interface OrderItemModifierGroup {
  /** Wire key `modifierGroupID`. */
  modifierGroupID: string;
  /** Wire key `modifierGroupName`. */
  modifierGroupName: string;
  modifiers: OrderItemModifier[];
}

export interface OrderItem {
  /** Wire key `itemID`. */
  itemID: string;
  name: string;
  quantity: number;
  weight: number | null;
  comment: string;
  /** Wire key `priceDisplay`. */
  priceDisplay: string;
  /** Wire key `originalItemPriceDisplay`. */
  originalItemPriceDisplay: string;
  /** Wire key `modifierGroups`. */
  modifierGroups: OrderItemModifierGroup[];
}

export interface OrderItemInfo {
  count: number;
  items: OrderItem[];
}

export interface OrderTimes {
  createdAt: string;
  acceptedAt: string;
  readyAt: string;
  deliveredAt: string;
  completedAt: string;
  cancelledAt: string;
  expiredAt: string;
  displayedAt: string;
  driverArriveRestoAt: string;
}

export interface OrderFare {
  currencySymbol: string;
  totalDisplay: string;
  subTotalDisplay: string;
  taxDisplay: string;
  deliveryFeeDisplay: string;
  promotionDisplay: string;
  passengerTotalDisplay: string;
}

export interface OrderMexOPT {
  isPreparationTaskDelayed: boolean;
  preparationTaskDelayedByMin: number;
  estimatedOPTDoneAt: string;
  actualOPT: string;
}

export interface OrderDetail {
  /** Wire key `orderID`. */
  orderID: string;
  /** Wire key `displayID`. */
  displayID: string;
  /** Wire key `bookingCode`. */
  bookingCode: string;
  state: string;
  eater: OrderEater;
  /** Wire key `itemInfo`. */
  itemInfo: OrderItemInfo;
  fare: OrderFare;
  times: OrderTimes;
  /** Wire key `mexOPT`. */
  mexOPT: OrderMexOPT;
}

/**
 * Lite subset of OrderDetail attached to completed/cancelled rows so
 * the dashboard can render the per-order item list without a second
 * click. Nullable — when the per-row fan-out hits a WAF / network
 * error, the row still renders with just the summary fields.
 *
 * Same wire-shape rules as ``OrderDetail``: camelCase keys everywhere
 * because FastAPI's ``response_model`` emits the Pydantic alias on
 * output (``OrderDetailLite`` declares ``alias="itemInfo"`` on
 * ``item_info``).
 */
export interface OrderDetailLite {
  orderID: string;
  displayID: string;
  eater: OrderEater;
  /** Wire key `itemInfo`. */
  itemInfo: OrderItemInfo;
  fare: OrderFare;
  times: OrderTimes;
}

export interface OrderListResponse {
  page_type: string;
  orders: OrderDetail[];
  warnings: string[];
}

const ORDERS_LIST_KEY = ["orders", "list"] as const;
const ORDER_DETAIL_KEY = ["orders", "detail"] as const;

async function fetchOrders(): Promise<OrderListResponse> {
  return api.get<OrderListResponse>("/api/orders");
}

async function fetchOrderDetail(orderId: string): Promise<OrderDetail> {
  return api.get<OrderDetail>(
    `/api/orders/${encodeURIComponent(orderId)}`,
  );
}

/**
 * Pull the preparing-order queue with full per-row detail.
 *
 * The dashboard polls every 60s and on focus, so `staleTime: 60s`
 * matches the polling cadence — no thundering herd, no stale UI. The
 * backend fans out one detail call per row in parallel, so we don't
 * need a `keepPreviousData` hack here.
 */
export function useOrders() {
  return useQuery({
    queryKey: ORDERS_LIST_KEY,
    queryFn: fetchOrders,
    staleTime: 60_000,
  });
}

/**
 * Pull the detail for a single order (used by the drill-in modal).
 *
 * Cached under the orders list so switching back to the list view
 * doesn't re-fetch the whole queue.
 */
export function useOrderDetail(orderId: string | null) {
  return useQuery({
    queryKey: [...ORDER_DETAIL_KEY, orderId ?? ""] as const,
    queryFn: () => fetchOrderDetail(orderId as string),
    enabled: Boolean(orderId),
    staleTime: 60_000,
  });
}

// ─── Multi-bucket history (Đang chuẩn bị / Sắp tới / Đã hoàn tất / Đã hủy) ──


export interface ScheduledOrder {
  orderID: string;
  displayID: string;
  eaterName: string;
  scheduledAt: string;
  state: string;
}

export interface CompletedOrder {
  orderID: string;
  displayID: string;
  priceDisplay: string;
  /** Wire key — Grab's daily-reports endpoint sends `updatedAt` for the completion timestamp on completed rows. */
  updatedAt: string;
  /**
   * Per-order item list + customer info (attached by the backend's
   * per-row detail fan-out). `null` if Grab rejected the detail call
   * — the row still renders with the summary fields.
   */
  detail: OrderDetailLite | null;
}

export interface CancelledOrder {
  orderID: string;
  displayID: string;
  /** Wire key `cancelledOriginalPriceDisplay`. */
  cancelledOriginalPriceDisplay: string;
  cancelledAt: string;
  cancelRole: string;
  /**
   * Same rationale as `CompletedOrder.detail` — per-row items so the
   * dashboard can show what was ordered before the cancellation.
   */
  detail: OrderDetailLite | null;
}

export interface OrderHistoryResponse {
  /** Wire key `dateRange` (with capital R — that's how Pydantic serializes the alias). */
  dateRange: { from: string; to: string };
  preparing: OrderDetail[];
  scheduled: ScheduledOrder[];
  completed: CompletedOrder[];
  cancelled: CancelledOrder[];
  warnings: string[];
}

// ─── Polling status ("đã chạy get lại đơn") ────────────────────────────────


export interface OrderPollStatus {
  lastPolledAt: string | null;
  nextPollAt: string | null;
  lastOrderCount: number;
  /**
   * One of `never` / `ok` / `empty` / `error`.
   *  - `ok`     → poll ran, ≥ 1 order found
   *  - `empty`  → poll ran, 0 orders ("đã chạy get lại đơn nhưng
   *               chưa tìm thấy đơn")
   *  - `error`  → poll failed (auth, network, …)
   *  - `never`  → the cron has never run for this store
   */
  lastStatus: "never" | "ok" | "empty" | "error" | string;
  message: string;
  storeId: number | null;
}

const ORDERS_HISTORY_KEY = ["orders", "history"] as const;
const ORDERS_POLL_STATUS_KEY = ["orders", "poll-status"] as const;

async function fetchOrdersHistory(
  fromDate: string,
  toDate: string,
): Promise<OrderHistoryResponse> {
  // URL query params stay snake_case — that's the FastAPI Query()
  // contract on the router.
  const params = new URLSearchParams({
    from_date: fromDate,
    to_date: toDate,
  });
  return api.get<OrderHistoryResponse>(
    `/api/orders/history?${params.toString()}`,
  );
}

async function fetchOrderPollStatus(): Promise<OrderPollStatus> {
  return api.get<OrderPollStatus>("/api/orders/poll-status");
}

/**
 * Fetch the four-bucket history for a date range.
 *
 * Used by the orders-page tab bar (Preparing / Scheduled / Completed
 * / Cancelled). One round-trip per filter change — the backend fans
 * out the four Grab calls in parallel and downgrades per-bucket
 * failures into the `warnings` array.
 *
 * `staleTime: 30s` keeps the UI snappy when the user toggles between
 * tabs without forcing an extra round-trip every click.
 */
export function useOrdersHistory(fromDate: string, toDate: string) {
  return useQuery({
    queryKey: [...ORDERS_HISTORY_KEY, fromDate, toDate] as const,
    queryFn: () => fetchOrdersHistory(fromDate, toDate),
    staleTime: 30_000,
  });
}

/**
 * Latest result of the 2-minute order cron for the current user's
 * store. Powers the "đã chạy get lại đơn lúc HH:MM — tìm thấy N đơn /
 * chưa tìm thấy đơn" banner.
 *
 * `staleTime: 30s` keeps the banner text in sync with the cron but
 * doesn't hammer the backend.
 */
export function useOrderPollStatus() {
  return useQuery({
    queryKey: ORDERS_POLL_STATUS_KEY,
    queryFn: fetchOrderPollStatus,
    staleTime: 30_000,
  });
}

export {
  ORDERS_LIST_KEY,
  ORDER_DETAIL_KEY,
  ORDERS_HISTORY_KEY,
  ORDERS_POLL_STATUS_KEY,
};
