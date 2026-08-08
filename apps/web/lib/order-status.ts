/**
 * The one place Grab's order-state enum becomes Vietnamese.
 *
 * There used to be two of these — one in `customers-client.tsx`, one in
 * `orders-client.tsx` — and they had already drifted: `ORDER_READY` read
 * "Sẵn sàng" on one page and "Sẵn sàng giao" on the other, only one knew
 * about `ORDER_SCHEDULED`, only the other knew about `ORDER_DELIVERING`.
 * The same order therefore described itself differently depending on
 * which tab you were looking at, which is exactly the sort of thing an
 * operator reads as "the dashboard is out of sync with Grab".
 *
 * Wording tracks the Grab Merchant app, so the two agree literally
 * rather than approximately: `ORDER_EXECUTING` is the state the app
 * shows as "Đang giao hàng".
 */

export type OrderStatusTone = "default" | "secondary" | "destructive" | "outline";

export interface OrderStatus {
  /** Vietnamese label, matching the Merchant app's wording. */
  label: string;
  tone: OrderStatusTone;
  /**
   * True when the state is one we have never seen. The label is then a
   * best-effort humanisation of the raw enum. Callers can use this to
   * flag it rather than presenting a guess as fact.
   */
  unknown: boolean;
}

const STATES: Record<string, { label: string; tone: OrderStatusTone }> = {
  ORDER_SCHEDULED: { label: "Đã lên lịch", tone: "outline" },

  ORDER_IN_PREPARE: { label: "Đang chuẩn bị", tone: "default" },
  ORDER_PREPARING: { label: "Đang chuẩn bị", tone: "default" },

  ORDER_READY: { label: "Sẵn sàng giao", tone: "outline" },

  // Grab's live "out for delivery" state. Observed on a real order that
  // the Merchant app displayed as "Đang giao hàng" while this dashboard
  // showed the bare enum, because neither old map listed it.
  ORDER_EXECUTING: { label: "Đang giao hàng", tone: "default" },
  ORDER_PICKED_UP: { label: "Đang giao hàng", tone: "default" },
  ORDER_DELIVERING: { label: "Đang giao hàng", tone: "default" },

  ORDER_DELIVERED: { label: "Hoàn tất", tone: "secondary" },
  ORDER_COMPLETED: { label: "Hoàn tất", tone: "secondary" },

  ORDER_CANCELLED: { label: "Đã hủy", tone: "destructive" },
  ORDER_REJECTED: { label: "Đã hủy", tone: "destructive" },
  ORDER_EXPIRED: { label: "Đã hủy", tone: "destructive" },
};

/**
 * Turn an unmapped enum into something a human can read.
 *
 * `ORDER_SOME_NEW_STATE` → `Some new state`. Grab adds states without
 * telling anyone — `ORDER_EXECUTING` arrived that way — and showing the
 * raw SCREAMING_CASE looks like a bug to an operator even when the data
 * is correct.
 */
function humanise(raw: string): string {
  const words = raw.replace(/^ORDER_/, "").replace(/_/g, " ").toLowerCase().trim();
  if (!words) return raw;
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function orderStatus(state: string | null | undefined): OrderStatus {
  const key = (state ?? "").trim().toUpperCase();
  if (!key) return { label: "—", tone: "outline", unknown: false };
  const known = STATES[key];
  if (known) return { ...known, unknown: false };
  return { label: humanise(key), tone: "outline", unknown: true };
}

/** True once Grab considers the order finished, either way. */
export function isTerminalOrderState(state: string | null | undefined): boolean {
  const key = (state ?? "").trim().toUpperCase();
  return (
    key === "ORDER_COMPLETED" ||
    key === "ORDER_DELIVERED" ||
    key === "ORDER_CANCELLED" ||
    key === "ORDER_REJECTED" ||
    key === "ORDER_EXPIRED"
  );
}
