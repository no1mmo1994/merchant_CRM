"use client";

import * as React from "react";
import {
  AlertTriangle,
  CalendarRange,
  CheckCircle2,
  ChevronRight,
  ClipboardList,
  Clock,
  History,
  Hourglass,
  ListChecks,
  Loader2,
  MapPin,
  Phone,
  ReceiptText,
  RefreshCw,
  StickyNote,
  User,
  XCircle,
} from "lucide-react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { CustomerTypeBadge } from "@/components/customers/CustomerTypeBadge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  useOrderDetail,
  useOrderPollStatus,
  useOrdersAutoRefresh,
  useOrdersHistory,
  type CancelledOrder,
  type CompletedOrder,
  type OrderDetail,
  type OrderItem,
  type OrderItemModifier,
  type OrderItemModifierGroup,
  type ScheduledOrder,
} from "@/lib/api/orders";
import { ApiError } from "@/lib/api";
import { toast } from "sonner";
import { orderStatus } from "@/lib/order-status";

// ─── helpers ─────────────────────────────────────────────────────────────────

/** Parse a locale-formatted VND string like `"305.000"` → 305000. */
function parseVnd(value: string | null | undefined): number {
  if (!value) return 0;
  const cleaned = value.replace(/[^\d\-]/g, "");
  const n = Number.parseInt(cleaned, 10);
  return Number.isFinite(n) ? n : 0;
}

/**
 * Format `12.000` → `"12.000 ₫"` (Vietnamese locale).
 *
 * Returns `""` for zero / non-finite values so the dashboard never
 * renders the misleading `"0 ₫"` placeholder. This matters for
 * Grab's per-order detail payload, which silently returns `"0"` for
 * item line prices that come from the preparing-pagination endpoint
 * (no per-item fare data there). The backend's ``_project_item``
 * keeps that `"0"` as-is — the frontend is the right place to
 * suppress it so the merchant doesn't think the item is free.
 */
function formatVnd(value: number): string {
  if (!Number.isFinite(value) || value === 0) return "";
  return `${value.toLocaleString("vi-VN")} ₫`;
}

/**
 * Thin adapter onto the shared `orderStatus` map.
 *
 * Was a second, divergent copy: it labelled `ORDER_READY` differently
 * from the customers page and, like that one, had no entry for
 * `ORDER_EXECUTING`.
 */
function stateLabel(state: string): string {
  return orderStatus(state).label;
}

/** Translate Grab's delay flag into a short Vietnamese status label. */
function delayLabel(
  mexOpt: { isPreparationTaskDelayed: boolean; preparationTaskDelayedByMin: number } | undefined,
): { text: string; tone: "warning" | "success" } {
  if (!mexOpt) return { text: "—", tone: "success" };
  if (mexOpt.isPreparationTaskDelayed) {
    const mins = mexOpt.preparationTaskDelayedByMin || 0;
    return { text: `⚠️ Đang bị chậm trễ (${mins} phút)`, tone: "warning" };
  }
  return { text: "✅ Đúng giờ", tone: "success" };
}

/** Map Grab's `state` enum → Badge tone for the overview list. */
function stateTone(state: string): "default" | "secondary" | "outline" | "destructive" {
  if (state === "ORDER_IN_PREPARE") return "default";
  if (state === "ORDER_READY") return "secondary";
  if (state.startsWith("ORDER_DELIVERING") || state === "ORDER_PICKED_UP") return "outline";
  if (state === "ORDER_COMPLETED" || state === "ORDER_DELIVERED") return "secondary";
  if (state === "ORDER_CANCELLED" || state === "ORDER_REJECTED") return "destructive";
  return "outline";
}

/** Render an ISO timestamp into a short HH:MM (Vietnam local) — used for the cron banner. */
function formatLocalTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  // UTC + 7 — same convention as the backend snapshot so the banner
  // text matches what the cron wrote.
  const local = new Date(d.getTime() + 7 * 60 * 60 * 1000);
  const hh = String(local.getUTCHours()).padStart(2, "0");
  const mm = String(local.getUTCMinutes()).padStart(2, "0");
  return `${hh}:${mm}`;
}

/** Render an ISO timestamp into a short date-time (Vietnam local) — for completed/cancelled rows. */
function formatLocalDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const local = new Date(d.getTime() + 7 * 60 * 60 * 1000);
  const dd = String(local.getUTCDate()).padStart(2, "0");
  const mm = String(local.getUTCMonth() + 1).padStart(2, "0");
  const yyyy = local.getUTCFullYear();
  const hh = String(local.getUTCHours()).padStart(2, "0");
  const mi = String(local.getUTCMinutes()).padStart(2, "0");
  return `${dd}/${mm}/${yyyy} ${hh}:${mi}`;
}

/** Today as YYYY-MM-DD in Vietnam local time (UTC+7). */
function todayIso(): string {
  const local = new Date(Date.now() + 7 * 60 * 60 * 1000);
  const yyyy = local.getUTCFullYear();
  const mm = String(local.getUTCMonth() + 1).padStart(2, "0");
  const dd = String(local.getUTCDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

/** `from` = 7 days ago, `to` = today (Vietnam local). */
function defaultRange(): { from: string; to: string } {
  const local = new Date(Date.now() + 7 * 60 * 60 * 1000);
  local.setUTCDate(local.getUTCDate() - 7);
  const yyyy = local.getUTCFullYear();
  const mm = String(local.getUTCMonth() + 1).padStart(2, "0");
  const dd = String(local.getUTCDate()).padStart(2, "0");
  const from = `${yyyy}-${mm}-${dd}`;
  return { from, to: todayIso() };
}

// ─── subcomponents ───────────────────────────────────────────────────────────

interface OrderOverviewCardProps {
  order: OrderDetail;
  onSelect: (orderId: string) => void;
}

/**
 * One row in the customer-overview list. Layout:
 *   - left:  customer name + displayID + phone + item count + total
 *   - right: state badge + delay badge + drill-in chevron
 */
function OrderOverviewCard({ order, onSelect }: OrderOverviewCardProps) {
  const total = parseVnd(order.fare.totalDisplay);
  const delay = delayLabel(order.mexOPT);
  const sLabel = stateLabel(order.state);

  return (
    <button
      type="button"
      onClick={() => onSelect(order.orderID)}
      className="flex w-full items-center justify-between gap-3 rounded-lg px-2 py-3 text-left transition-colors hover:bg-(--color-surface-2) focus:outline-none focus-visible:ring-2 focus-visible:ring-(--color-brand)"
    >
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-semibold text-(--color-foreground)">
            {order.eater.name || "Khách lẻ"}
          </span>
          <span className="shrink-0 rounded bg-(--color-surface-2) px-1.5 py-0.5 font-mono text-xs text-(--color-muted-foreground)">
            {order.displayID || order.orderID.slice(-6)}
          </span>
          <CustomerTypeBadge isNew={order.isNewCustomer} className="shrink-0" />
        </div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-(--color-muted-foreground)">
          {order.eater.mobileNumber && (
            <span className="inline-flex items-center gap-1">
              <Phone className="h-3 w-3" />
              {order.eater.mobileNumber}
            </span>
          )}
          <span>
            {order.itemInfo.count} món
          </span>
          <span>{formatVnd(total)}</span>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <Badge variant={stateTone(order.state)}>{sLabel}</Badge>
        {order.mexOPT.isPreparationTaskDelayed && (
          <Badge variant="destructive" className="hidden md:inline-flex">
            {delay.text}
          </Badge>
        )}
        <ChevronRight className="h-4 w-4 text-(--color-muted-foreground)" />
      </div>
    </button>
  );
}

interface ModifierChipProps {
  group: OrderItemModifierGroup;
}
function ModifierGroup({ group }: ModifierChipProps) {
  if (!group.modifiers || group.modifiers.length === 0) return null;
  return (
    <div className="space-y-1">
      {group.modifierGroupName && (
        <div className="text-xs font-medium uppercase tracking-wide text-(--color-muted-foreground)">
          {group.modifierGroupName}
        </div>
      )}
      <ul className="flex flex-wrap gap-1.5">
        {group.modifiers.map((m: OrderItemModifier, idx) => (
          <li
            key={`${group.modifierGroupID}-${m.modifierID || idx}`}
            className="inline-flex items-center gap-1.5 rounded-full bg-(--color-surface-2) px-2.5 py-1 text-xs text-(--color-foreground)"
          >
            <span>
              {m.modifierName} <span className="text-(--color-muted-foreground)">×{m.quantity}</span>
            </span>
            <span className="font-mono text-(--color-muted-foreground)">
              {parseVnd(m.priceDisplay) > 0 ? `+${formatVnd(parseVnd(m.priceDisplay))}` : ""}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

interface ItemRowProps {
  item: OrderItem;
}
function ItemRow({ item }: ItemRowProps) {
  return (
    <div className="space-y-2 rounded-md border border-(--color-border) bg-(--color-surface) p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="text-sm font-medium text-(--color-foreground)">
          <span className="text-(--color-brand)">{item.quantity}×</span> {item.name}
        </div>
        <div className="font-mono text-xs text-(--color-muted-foreground)">
          {formatVnd(parseVnd(item.priceDisplay))}
        </div>
      </div>
      {item.comment && (
        <div className="flex items-start gap-1.5 rounded bg-amber-50 px-2 py-1 text-xs text-amber-900">
          <StickyNote className="mt-0.5 h-3 w-3 shrink-0" />
          <span>{item.comment}</span>
        </div>
      )}
      {item.modifierGroups.length > 0 && (
        <div className="space-y-1.5">
          {item.modifierGroups.map((g) => (
            <ModifierGroup key={g.modifierGroupID || g.modifierGroupName} group={g} />
          ))}
        </div>
      )}
    </div>
  );
}

interface OrderDetailDialogProps {
  orderId: string | null;
  onClose: () => void;
}

function OrderDetailDialog({ orderId, onClose }: OrderDetailDialogProps) {
  const { data, isLoading, error } = useOrderDetail(orderId);
  const open = Boolean(orderId);

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="max-h-[88vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <ReceiptText className="h-4 w-4" />
            Chi tiết đơn hàng
          </DialogTitle>
          <DialogDescription>
            Đồng bộ trực tiếp từ Grab Merchant — mỗi lần mở đều tải lại dữ liệu mới nhất.
          </DialogDescription>
        </DialogHeader>

        {isLoading && (
          <div className="space-y-3">
            <Skeleton className="h-5 w-1/3" />
            <Skeleton className="h-4 w-2/3" />
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-16 w-full" />
          </div>
        )}

        {error && !isLoading && (
          <div className="flex items-start gap-2 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-900">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <div className="font-medium">Không tải được chi tiết đơn hàng.</div>
              <div className="mt-0.5 text-xs text-red-800">
                {error instanceof ApiError ? error.message : "Đã xảy ra lỗi không xác định."}
              </div>
            </div>
          </div>
        )}

        {data && !isLoading && (
          <div className="space-y-4">
            {/* Header strip */}
            <div className="space-y-2 rounded-md border border-(--color-border) bg-(--color-surface-2) p-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-sm font-semibold text-(--color-foreground)">
                  {data.displayID || data.orderID}
                </span>
                <Badge variant={stateTone(data.state)}>
                  {stateLabel(data.state)}
                </Badge>
                <Badge variant={delayLabel(data.mexOPT).tone === "warning" ? "destructive" : "secondary"}>
                  {delayLabel(data.mexOPT).tone === "warning" ? (
                    <AlertTriangle className="mr-1 h-3 w-3" />
                  ) : (
                    <CheckCircle2 className="mr-1 h-3 w-3" />
                  )}
                  {delayLabel(data.mexOPT).text}
                </Badge>
              </div>
              {data.bookingCode && (
                <div className="text-xs text-(--color-muted-foreground)">
                  Booking: <span className="font-mono">{data.bookingCode}</span>
                </div>
              )}
            </div>

            {/* Customer block */}
            <div className="space-y-2 rounded-md border border-(--color-border) p-3">
              <div className="flex items-center gap-2 text-sm font-semibold text-(--color-foreground)">
                <User className="h-4 w-4" />
                Khách hàng
                <CustomerTypeBadge isNew={data.isNewCustomer} className="ml-auto" />
              </div>
              <div className="space-y-1 text-sm">
                <div className="font-medium">{data.eater.name || "Khách lẻ"}</div>
                {data.eater.mobileNumber && (
                  <div className="inline-flex items-center gap-1.5 text-xs text-(--color-muted-foreground)">
                    <Phone className="h-3 w-3" />
                    <a
                      className="hover:underline"
                      href={`tel:${data.eater.mobileNumber}`}
                    >
                      {data.eater.mobileNumber}
                    </a>
                  </div>
                )}
                {data.eater.address && (
                  <div className="flex items-start gap-1.5 text-xs text-(--color-muted-foreground)">
                    <MapPin className="mt-0.5 h-3 w-3 shrink-0" />
                    <span>{data.eater.address}</span>
                  </div>
                )}
                {data.eater.comment && (
                  <div className="mt-1 flex items-start gap-1.5 rounded bg-amber-50 px-2 py-1.5 text-xs text-amber-900">
                    <StickyNote className="mt-0.5 h-3 w-3 shrink-0" />
                    <span>{data.eater.comment}</span>
                  </div>
                )}
              </div>
            </div>

            {/* Items */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <div className="text-sm font-semibold text-(--color-foreground)">
                  Danh sách món ({data.itemInfo.count})
                </div>
                <div className="text-sm font-semibold text-(--color-brand)">
                  {formatVnd(parseVnd(data.fare.totalDisplay))}
                </div>
              </div>
              <div className="space-y-2">
                {data.itemInfo.items.length === 0 && (
                  <div className="rounded-md border border-dashed border-(--color-border) p-4 text-center text-xs text-(--color-muted-foreground)">
                    Đơn hàng chưa có món nào.
                  </div>
                )}
                {data.itemInfo.items.map((item, idx) => (
                  <ItemRow key={item.itemID || `${item.name}-${idx}`} item={item} />
                ))}
              </div>
            </div>

            {/* Fare breakdown */}
            <div className="space-y-1 rounded-md border border-(--color-border) p-3 text-xs">
              <div className="flex justify-between">
                <span className="text-(--color-muted-foreground)">Tạm tính</span>
                <span className="font-mono">{formatVnd(parseVnd(data.fare.subTotalDisplay))}</span>
              </div>
              {parseVnd(data.fare.deliveryFeeDisplay) > 0 && (
                <div className="flex justify-between">
                  <span className="text-(--color-muted-foreground)">Phí giao hàng</span>
                  <span className="font-mono">{formatVnd(parseVnd(data.fare.deliveryFeeDisplay))}</span>
                </div>
              )}
              {parseVnd(data.fare.taxDisplay) > 0 && (
                <div className="flex justify-between">
                  <span className="text-(--color-muted-foreground)">Thuế</span>
                  <span className="font-mono">{formatVnd(parseVnd(data.fare.taxDisplay))}</span>
                </div>
              )}
              {parseVnd(data.fare.promotionDisplay) > 0 && (
                <div className="flex justify-between text-emerald-700">
                  <span>Khuyến mãi</span>
                  <span className="font-mono">-{formatVnd(parseVnd(data.fare.promotionDisplay))}</span>
                </div>
              )}
              <div className="flex justify-between border-t border-(--color-border) pt-1 text-sm font-semibold">
                <span>Tổng cộng</span>
                <span className="font-mono text-(--color-brand)">
                  {formatVnd(parseVnd(data.fare.totalDisplay))}
                </span>
              </div>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

// ─── Polling banner ("đã chạy get lại đơn …") ────────────────────────────────

interface PollBannerProps {
  /** Date range to show next-poll estimate for (next poll is independent of range, kept for future use). */
  fromDate?: string;
  toDate?: string;
}

function PollBanner(_props: PollBannerProps) {
  const { data, isLoading, error } = useOrderPollStatus();

  // Default to a friendly "loading" state so the banner row is always
  // present (avoids layout shift when the cron has never run yet).
  if (isLoading) {
    return (
      <div
        role="status"
        aria-live="polite"
        className="flex items-center gap-2 rounded-md border border-(--color-border) bg-(--color-surface-2) px-3 py-2 text-xs text-(--color-muted-foreground)"
      >
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        <span>Đang kiểm tra trạng thái get lại đơn…</span>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div
        role="status"
        aria-live="polite"
        className="flex items-center gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900"
      >
        <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
        <span>
          Không tải được trạng thái get lại đơn — vẫn đang thử lại trong nền.
        </span>
      </div>
    );
  }

  // Status mapping → banner copy + tone.
  // Banner always surfaces the latest message the cron wrote so the
  // operator can confirm the job ran.
  const status = data.lastStatus;
  const message = data.message || "Chưa có thông báo từ cron.";
  const lastAt = formatLocalTime(data.lastPolledAt);

  let bannerClass =
    "rounded-md border border-(--color-border) bg-(--color-surface-2) px-3 py-2 text-xs text-(--color-foreground)";
  let Icon: React.ComponentType<{ className?: string }> = Clock;
  if (status === "ok") {
    bannerClass =
      "rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-900";
    Icon = CheckCircle2;
  } else if (status === "empty") {
    bannerClass =
      "rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900";
    Icon = AlertTriangle;
  } else if (status === "error") {
    bannerClass =
      "rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-900";
    Icon = XCircle;
  }

  return (
    <div role="status" aria-live="polite" className={`flex items-center gap-2 ${bannerClass}`}>
      <Icon className="h-3.5 w-3.5 shrink-0" />
      <span className="flex-1 truncate">{message}</span>
      {status !== "never" && (
        <span className="shrink-0 font-mono text-[11px] opacity-70">cập nhật {lastAt}</span>
      )}
    </div>
  );
}

// ─── Bucket list views ───────────────────────────────────────────────────────

interface ScheduledListProps {
  rows: ScheduledOrder[];
  emptyHint: string;
}
function ScheduledList({ rows, emptyHint }: ScheduledListProps) {
  if (rows.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-(--color-border) p-6 text-center text-sm text-(--color-muted-foreground)">
        {emptyHint}
      </div>
    );
  }
  return (
    <div className="divide-y divide-(--color-border)">
      {rows.map((r) => (
        <div
          key={r.orderID || r.displayID}
          className="flex items-center justify-between gap-3 px-2 py-3"
        >
          <div className="min-w-0 flex-1 space-y-1">
            <div className="flex items-center gap-2">
              <span className="truncate text-sm font-semibold text-(--color-foreground)">
                {r.eaterName || "Khách lẻ"}
              </span>
              <span className="shrink-0 rounded bg-(--color-surface-2) px-1.5 py-0.5 font-mono text-xs text-(--color-muted-foreground)">
                {r.displayID || r.orderID?.slice(-6)}
              </span>
            </div>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-(--color-muted-foreground)">
              <span className="inline-flex items-center gap-1">
                <Hourglass className="h-3 w-3" />
                {formatLocalDateTime(r.scheduledAt)}
              </span>
              {r.state && <Badge variant="outline">{stateLabel(r.state)}</Badge>}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

interface CompletedListProps {
  rows: CompletedOrder[];
  emptyHint: string;
}
function CompletedList({ rows, emptyHint }: CompletedListProps) {
  if (rows.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-(--color-border) p-6 text-center text-sm text-(--color-muted-foreground)">
        {emptyHint}
      </div>
    );
  }
  return (
    <div className="divide-y divide-(--color-border)">
      {rows.map((r) => (
        <div
          key={r.orderID || r.displayID}
          className="flex items-start justify-between gap-3 px-2 py-3"
        >
          <div className="min-w-0 flex-1 space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-sm font-semibold text-(--color-foreground)">
                {r.displayID || r.orderID?.slice(-6)}
              </span>
              <Badge variant="secondary">Hoàn tất</Badge>
              {r.detail?.eater?.name && (
                <span className="truncate text-xs text-(--color-muted-foreground)">
                  · {r.detail.eater.name}
                </span>
              )}
              <CustomerTypeBadge isNew={r.detail?.isNewCustomer} />
            </div>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-(--color-muted-foreground)">
              <span className="inline-flex items-center gap-1">
                <CheckCircle2 className="h-3 w-3" />
                {formatLocalDateTime(r.updatedAt)}
              </span>
            </div>
            <OrderItemsBlock detail={r.detail} />
          </div>
          <div className="shrink-0 text-sm font-semibold text-(--color-brand)">
            {formatVnd(parseVnd(r.priceDisplay))}
          </div>
        </div>
      ))}
    </div>
  );
}

interface CancelledListProps {
  rows: CancelledOrder[];
  emptyHint: string;
}
function CancelledList({ rows, emptyHint }: CancelledListProps) {
  if (rows.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-(--color-border) p-6 text-center text-sm text-(--color-muted-foreground)">
        {emptyHint}
      </div>
    );
  }
  return (
    <div className="divide-y divide-(--color-border)">
      {rows.map((r) => (
        <div
          key={r.orderID || r.displayID}
          className="flex items-start justify-between gap-3 px-2 py-3"
        >
          <div className="min-w-0 flex-1 space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-sm font-semibold text-(--color-foreground)">
                {r.displayID || r.orderID?.slice(-6)}
              </span>
              <Badge variant="destructive">Đã hủy</Badge>
              {r.cancelRole && (
                <Badge variant="outline">{r.cancelRole}</Badge>
              )}
              {r.detail?.eater?.name && (
                <span className="truncate text-xs text-(--color-muted-foreground)">
                  · {r.detail.eater.name}
                </span>
              )}
              <CustomerTypeBadge isNew={r.detail?.isNewCustomer} />
            </div>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-(--color-muted-foreground)">
              <span className="inline-flex items-center gap-1">
                <XCircle className="h-3 w-3" />
                {formatLocalDateTime(r.cancelledAt)}
              </span>
            </div>
            <OrderItemsBlock detail={r.detail} />
          </div>
          <div className="shrink-0 text-sm font-semibold text-(--color-foreground)">
            {formatVnd(parseVnd(r.cancelledOriginalPriceDisplay))}
          </div>
        </div>
      ))}
    </div>
  );
}

/**
 * Renders the per-order item list under each completed/cancelled row.
 * Falls back to a hint when the lite-detail fan-out didn't return
 * anything (network blip, WAF rejection) so the row still renders
 * without the item breakdown.
 */
function OrderItemsBlock({
  detail,
}: {
  detail: CompletedOrder["detail"] | CancelledOrder["detail"];
}) {
  if (!detail) {
    return (
      <p className="text-[11px] italic text-(--color-muted-foreground)">
        Không tải được chi tiết sản phẩm.
      </p>
    );
  }
  // Wire field is ``itemInfo`` (camelCase) — see ``orders.ts`` docblock
  // for the full rationale (FastAPI's response_model emits aliases when
  // the schema declares them + ``populate_by_name=True``). The early
  // dashboard prototype assumed snake_case and rendered blanks; this
  // was the root cause of the "không hiển thị sản phẩm đi kèm" bug.
  const items = detail.itemInfo?.items ?? [];
  if (items.length === 0) {
    return null;
  }
  return (
    <ul className="space-y-0.5 pl-1 pt-1 text-xs text-(--color-foreground)">
      {items.map((it) => {
        const linePrice = parseVnd(it.priceDisplay);
        return (
          <li
            key={it.itemID || `${it.name}-${it.quantity}`}
            className="flex items-baseline justify-between gap-2"
          >
            <span className="min-w-0 truncate">
              <span className="font-medium">{it.name}</span>
              <span className="text-(--color-muted-foreground)"> ×{it.quantity}</span>
              {it.modifierGroups && it.modifierGroups.length > 0 && (
                <span className="ml-1 text-[11px] text-(--color-muted-foreground)">
                  {it.modifierGroups
                    .flatMap((g) => g.modifiers ?? [])
                    .map((m) => m.modifierName)
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              )}
              {it.comment && (
                <span className="ml-1 text-[11px] italic text-(--color-muted-foreground)">
                  ({it.comment})
                </span>
              )}
            </span>
            <span className="shrink-0 font-mono text-[11px] text-(--color-muted-foreground)">
              {formatVnd(linePrice)}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

// ─── main ────────────────────────────────────────────────────────────────────

type BucketKey = "preparing" | "scheduled" | "completed" | "cancelled";

interface BucketTab {
  key: BucketKey;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  hint: string;
}

const BUCKETS: BucketTab[] = [
  {
    key: "preparing",
    label: "Đang chuẩn bị",
    icon: ClipboardList,
    hint: "Hiện không có đơn hàng nào đang chuẩn bị.",
  },
  {
    key: "scheduled",
    label: "Sắp tới",
    icon: Hourglass,
    hint: "Chưa có đơn đặt trước nào trong hàng chờ.",
  },
  {
    key: "completed",
    label: "Đã hoàn tất",
    icon: CheckCircle2,
    hint: "Chưa có đơn hoàn tất nào trong khoảng thời gian đã chọn.",
  },
  {
    key: "cancelled",
    label: "Đã hủy",
    icon: XCircle,
    hint: "Chưa có đơn hủy nào trong khoảng thời gian đã chọn.",
  },
];

export function OrdersClient() {
  // Refresh the order list whenever the backend's 30s cron reports a new
  // poll. Without it this page never updated on its own — an order that
  // went out for delivery and then completed kept showing whatever state
  // it had when the tab was opened.
  useOrdersAutoRefresh();

  const initial = React.useMemo(defaultRange, []);
  const [fromDate, setFromDate] = React.useState<string>(initial.from);
  const [toDate, setToDate] = React.useState<string>(initial.to);
  const [activeBucket, setActiveBucket] = React.useState<BucketKey>("preparing");
  const [selectedId, setSelectedId] = React.useState<string | null>(null);

  const historyQuery = useOrdersHistory(fromDate, toDate);
  const { data, isLoading, error, refetch, isRefetching } = historyQuery;

  const handleRefresh = React.useCallback(() => {
    refetch().catch(() => undefined);
  }, [refetch]);

  const handleSelect = React.useCallback((orderId: string) => {
    setSelectedId(orderId);
  }, []);

  const handleClose = React.useCallback(() => {
    setSelectedId(null);
  }, []);

  React.useEffect(() => {
    if (error instanceof ApiError) {
      toast.error("Không tải được danh sách đơn hàng", {
        description: error.message,
      });
    } else if (error) {
      toast.error("Không tải được danh sách đơn hàng");
    }
  }, [error]);

  const preparing = data?.preparing ?? [];
  const scheduled = data?.scheduled ?? [];
  const completed = data?.completed ?? [];
  const cancelled = data?.cancelled ?? [];
  const warnings = data?.warnings ?? [];

  const preparingCount = preparing.filter((o) => o.state === "ORDER_IN_PREPARE").length;
  const delayedCount = preparing.filter((o) => o.mexOPT.isPreparationTaskDelayed).length;
  const scheduledCount = scheduled.length;
  const completedCount = completed.length;
  const cancelledCount = cancelled.length;

  const activeBucketMeta =
    BUCKETS.find((b) => b.key === activeBucket) ?? BUCKETS[0];

  return (
    <div className="space-y-6">
      {/* KPI tiles */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card className="border-(--color-border)">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Tổng đơn đang chuẩn bị</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{isLoading ? "—" : preparing.length}</div>
          </CardContent>
        </Card>
        <Card className="border-(--color-border)">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Đơn đang nấu</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-(--color-brand)">
              {isLoading ? "—" : preparingCount}
            </div>
          </CardContent>
        </Card>
        <Card className="border-(--color-border)">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Đơn bị chậm trễ</CardTitle>
          </CardHeader>
          <CardContent>
            <div className={`text-2xl font-bold ${delayedCount > 0 ? "text-amber-700" : ""}`}>
              {isLoading ? "—" : delayedCount}
            </div>
          </CardContent>
        </Card>
        <Card className="border-(--color-border)">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Đơn sắp tới</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {isLoading ? "—" : scheduledCount}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* 2-min poll banner */}
      <PollBanner fromDate={fromDate} toDate={toDate} />

      {/* History card with bucket tabs */}
      <Card className="border-(--color-border)">
        <CardHeader className="flex flex-row items-center justify-between space-y-0 gap-2">
          <CardTitle className="flex items-center gap-2 text-base">
            <History className="h-4 w-4" />
            Đơn hàng — theo khoảng thời gian
          </CardTitle>
          <Button
            variant="ghost"
            size="sm"
            onClick={handleRefresh}
            disabled={isLoading || isRefetching}
          >
            {isRefetching ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
            <span className="ml-1.5">Làm mới</span>
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Date range + bucket tabs */}
          <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
            <div className="flex flex-col gap-2 md:flex-row md:items-end md:gap-3">
              <label className="flex flex-col gap-1 text-xs text-(--color-muted-foreground)">
                <span className="inline-flex items-center gap-1">
                  <CalendarRange className="h-3 w-3" />
                  Từ ngày
                </span>
                <input
                  type="date"
                  value={fromDate}
                  max={toDate}
                  onChange={(e) => setFromDate(e.currentTarget.value)}
                  className="rounded-md border border-(--color-border) bg-(--color-surface) px-2 py-1.5 text-sm text-(--color-foreground) focus:outline-none focus-visible:ring-2 focus-visible:ring-(--color-brand)"
                />
              </label>
              <label className="flex flex-col gap-1 text-xs text-(--color-muted-foreground)">
                <span>Đến ngày</span>
                <input
                  type="date"
                  value={toDate}
                  min={fromDate}
                  onChange={(e) => setToDate(e.currentTarget.value)}
                  className="rounded-md border border-(--color-border) bg-(--color-surface) px-2 py-1.5 text-sm text-(--color-foreground) focus:outline-none focus-visible:ring-2 focus-visible:ring-(--color-brand)"
                />
              </label>
              <div className="hidden text-xs text-(--color-muted-foreground) md:block">
                <ListChecks className="mr-1 inline h-3 w-3" />
                Hoàn tất: <span className="font-semibold text-(--color-foreground)">{completedCount}</span>{" "}
                · Hủy:{" "}
                <span className="font-semibold text-(--color-foreground)">{cancelledCount}</span>
              </div>
            </div>
          </div>

          {/* Tabs */}
          <div className="flex flex-wrap gap-2 border-b border-(--color-border) pb-2">
            {BUCKETS.map((b) => {
              const Icon = b.icon;
              const isActive = b.key === activeBucket;
              const count =
                b.key === "preparing"
                  ? preparing.length
                  : b.key === "scheduled"
                    ? scheduled.length
                    : b.key === "completed"
                      ? completed.length
                      : cancelled.length;
              return (
                <button
                  key={b.key}
                  type="button"
                  onClick={() => setActiveBucket(b.key)}
                  className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                    isActive
                      ? "bg-(--color-brand) text-(--color-brand-foreground, white)"
                      : "bg-(--color-surface-2) text-(--color-foreground) hover:bg-(--color-surface-3, --color-surface-2)"
                  }`}
                >
                  <Icon className="h-3.5 w-3.5" />
                  {b.label}
                  <span
                    className={`ml-1 inline-flex min-w-5 justify-center rounded-full px-1.5 text-[11px] ${
                      isActive
                        ? "bg-white/20 text-white"
                        : "bg-(--color-surface) text-(--color-muted-foreground)"
                    }`}
                  >
                    {isLoading ? "—" : count}
                  </span>
                </button>
              );
            })}
          </div>

          {/* Active bucket body */}
          {isLoading && (
            <div className="space-y-2">
              <Skeleton className="h-14 w-full" />
              <Skeleton className="h-14 w-full" />
              <Skeleton className="h-14 w-full" />
            </div>
          )}

          {!isLoading && activeBucket === "preparing" && (
            <>
              {preparing.length === 0 ? (
                <div className="rounded-md border border-dashed border-(--color-border) p-6 text-center text-sm text-(--color-muted-foreground)">
                  {warnings.length > 0
                    ? warnings.join(" ")
                    : activeBucketMeta.hint}
                </div>
              ) : (
                <div className="divide-y divide-(--color-border)">
                  {preparing.map((o) => (
                    <OrderOverviewCard
                      key={o.orderID}
                      order={o}
                      onSelect={handleSelect}
                    />
                  ))}
                </div>
              )}
            </>
          )}

          {!isLoading && activeBucket === "scheduled" && (
            <ScheduledList rows={scheduled} emptyHint={activeBucketMeta.hint} />
          )}

          {!isLoading && activeBucket === "completed" && (
            <CompletedList rows={completed} emptyHint={activeBucketMeta.hint} />
          )}

          {!isLoading && activeBucket === "cancelled" && (
            <CancelledList rows={cancelled} emptyHint={activeBucketMeta.hint} />
          )}

          {/* Warnings footer — visible across all buckets */}
          {warnings.length > 0 && (
            <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
              {warnings.map((w, i) => (
                <div key={i}>⚠️ {w}</div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <OrderDetailDialog orderId={selectedId} onClose={handleClose} />
    </div>
  );
}