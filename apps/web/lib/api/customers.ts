import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { OrderDetailLite, OrderItem } from "@/lib/api/orders";

/**
 * Customers / sources / order-info API surface.
 *
 * Mirrors services/api/app/routers/customers.py — a single
 * `/api/customers/overview` round-trip returning three
 * pre-aggregated lists over the OrderArchive snapshot the cron
 * writes every 30s.
 *
 * Wire shape:
 *   GET /api/customers/overview → CustomersOverviewResponse
 *
 *   response.customers[]  — distinct customers grouped by
 *                            eater.mobileNumber
 *   response.sources[]    — distinct merchant_id buckets
 *   response.orders[]     — every archived order, hydrated via
 *                            OrderDetailLite, plus the
 *                            archive's first/last-seen +
 *                            current state
 *
 * IMPORTANT — camelCase wire shape (same as `lib/api/orders.ts`):
 *   FastAPI emits the Pydantic alias verbatim. Fields like
 *   `mobileNumber`, `orderCount`, `firstSeenAt`, `merchantId`
 *   arrive camelCase — NOT snake_case — and the dashboard's
 *   JSX is wired to those exact keys.
 */

export interface CustomerSummary {
  /** Wire key `mobileNumber`. Empty string when the order has no eater phone on file. */
  mobileNumber: string;
  name: string;
  address: string;
  /** Wire key `orderCount` — total distinct orders from this customer. */
  orderCount: number;
  /**
   * Wire key `totalDisplay` — most recent order total as a
   * locale-formatted string (`"65.000"`, `"1.234.567"`). Kept
   * string, not float, to avoid lossy round-trip.
   */
  totalDisplay: string;
  /** Wire key `lastOrderAt` — ISO timestamp of the most-recent archived row for this customer. */
  lastOrderAt: string | null;
  /** Wire key `lastState` — the archive's `state` at last sight (e.g. `ORDER_IN_PREPARE` / `ORDER_COMPLETED`). */
  lastState: string;
  /**
   * Wire key `isNewCustomer` — Grab's verdict as of this customer's most
   * recent order. `null` when Grab sent no flag.
   *
   * Not the same question as `orderCount`: that counts what this
   * dashboard has archived, while Grab knows the customer's whole
   * history with the store, including orders placed before the dashboard
   * existed. A customer with `orderCount: 1` can still be a returning
   * one.
   */
  isNewCustomer: boolean | null;
}

export interface SourceSummary {
  /** Wire key `merchantId` — mã cửa hàng / chi nhánh. */
  merchantId: string;
  /** Wire key `address` — branch address from Store.address. Empty when no Store row matched (archived from a removed branch) or when Grab's business_attributes returned no address. */
  address: string;
  /** Wire key `name` — human-readable shop name from Store.name. Used as the subtitle fallback when `address` is empty so the merchant can identify the branch without leaving the page. */
  name: string;
  /**
   * Wire key `region` — auto-derived city/province (e.g.
   * `"Đà Nẵng"`, `"TP.HCM"`). Populated by the backend at write
   * time from `Store.address` via `app.core.region.extract_city`.
   * Empty when the address doesn't resolve to a known city OR
   * when no address was ever persisted. The dashboard renders
   * this as a badge next to the address so the operator can
   * see at a glance which region this branch belongs to — and
   * the partner API uses it to label the `source` field as
   * `"GF " + region`.
   */
  region: string;
  /** Wire key `orderCount` — total distinct orders under this merchant_id. */
  orderCount: number;
  /** Wire key `distinctCustomers` — count of unique `mobileNumber` values under this merchant_id. */
  distinctCustomers: number;
}

export interface OrderSummary {
  /** Wire key `orderId`. */
  orderId: string;
  /** Wire key `displayId`. */
  displayId: string;
  state: string;
  /** Wire key `firstSeenAt` — when the cron first archived this order. */
  firstSeenAt: string;
  /** Wire key `lastSeenAt` — when the cron last refreshed this order. */
  lastSeenAt: string;
  /** Hydrated via OrderDetailLite.from_raw — same shape as the orders-page card detail. */
  detail: OrderDetailLite;
}

/** Re-export so the customers-client can render items without a second import. */
export type { OrderItem };

/** Trading figures for one slice of customers. */
export interface CustomerMixBucket {
  /** Every archived order in this slice, cancelled included. */
  orders: number;
  /** Wire key `cancelledOrders`. */
  cancelledOrders: number;
  /** Distinct phone numbers. A person can appear in both new and returning. */
  customers: number;
  /** Wire key `revenueVnd` — cancelled orders excluded. */
  revenueVnd: number;
  /** Wire key `avgOrderValue` — over non-cancelled orders only. */
  avgOrderValue: number;
}

/**
 * New versus returning customers.
 *
 * `unknown` holds orders where Grab sent no flag, kept separate so a gap
 * in the data never reads as a finding about customer behaviour.
 */
export interface CustomerMix {
  new: CustomerMixBucket;
  returning: CustomerMixBucket;
  unknown: CustomerMixBucket;
  /** Wire key `newOrderShare`, 0–1. `null` when there are no orders yet. */
  newOrderShare: number | null;
  /** Wire key `newRevenueShare`, 0–1. `null` when nothing was earned. */
  newRevenueShare: number | null;
}

export interface CustomersOverviewResponse {
  customers: CustomerSummary[];
  sources: SourceSummary[];
  orders: OrderSummary[];
  /** Wire key `customerMix`. */
  customerMix: CustomerMix;
}

const CUSTOMERS_OVERVIEW_KEY = ["customers", "overview"] as const;

async function fetchCustomersOverview(): Promise<CustomersOverviewResponse> {
  return api.get<CustomersOverviewResponse>("/api/customers/overview");
}

/**
 * Pull the three-lens customer / source / order view.
 *
 * One round-trip powers all three tabs. The backend reuses the
 * in-memory scan of `OrderArchive` rows so the cost is bounded
 * by the store's archive size, not multiplied by three.
 *
 * Polling cadence:
 *   The cron writes a new OrderArchive row every 30 s. We poll
 *   every 10 s so the dashboard surfaces state transitions
 *   (Đang chuẩn bị → Hoàn tất / Đã hủy) within ~10-40 s of Grab
 *   reflecting them — combined with the 30 s cron + 1-2 s per-row
 *   fan-out, the user sees the change without clicking "Tải lại".
 *   `staleTime` matches `refetchInterval` so the refetch always
 *   fires on the polling cadence. `placeholderData` keeps the
 *   previous snapshot on screen during the refetch — no flicker.
 */
export function useCustomersOverview() {
  return useQuery({
    queryKey: CUSTOMERS_OVERVIEW_KEY,
    queryFn: fetchCustomersOverview,
    staleTime: 10_000,
    refetchInterval: 10_000,
    placeholderData: (prev) => prev,
  });
}

export { CUSTOMERS_OVERVIEW_KEY };
