"use client";

import * as React from "react";
import {
  AlertTriangle,
  ClipboardList,
  Clock,
  Hourglass,
  Loader2,
  MapPin,
  Phone,
  ReceiptText,
  Store,
  User,
} from "lucide-react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useCustomersOverview } from "@/lib/api/customers";
import type {
  CustomerSummary,
  OrderItem,
  OrderSummary,
  SourceSummary,
} from "@/lib/api/customers";

// ── helpers ─────────────────────────────────────────────────────────────────

/** Parse a locale-formatted VND string like `"305.000"` → 305000. */
function parseVnd(value: string | null | undefined): number {
  if (!value) return 0;
  const cleaned = value.replace(/[^\d\-]/g, "");
  const n = Number.parseInt(cleaned, 10);
  return Number.isFinite(n) ? n : 0;
}

/** Detect a Grab-anonymised eater block.
 *
 * Grab's per-order detail endpoint strips the customer identity
 * for some cancelled / completed orders: ``name`` arrives as the
 * literal string ``"***"`` and ``mobileNumber`` is empty. The
 * backend passes these values through unchanged so the frontend
 * can decide how to render them — this helper is the single
 * source of truth for that detection (used by both
 * ``CustomerCard`` and ``OrderRow``).
 */
function isAnonymisedEater(name: string | undefined, phone: string | undefined): boolean {
  const n = (name ?? "").trim();
  const p = (phone ?? "").trim();
  return n === "***" || (n === "" && p === "");
}

/** Format a number as Vietnamese locale `"12.000"`. Zero → `""`. */
function formatVnd(value: number): string {
  if (!Number.isFinite(value) || value === 0) return "";
  return `${value.toLocaleString("vi-VN")} ₫`;
}

/** Format a Date (or ISO string) into a short `HH:MM DD/MM` label. */
function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  const mo = String(d.getMonth() + 1).padStart(2, "0");
  return `${hh}:${mm} ${dd}/${mo}`;
}

/** Map Grab's raw state to a Vietnamese label + badge variant. */
function stateBadge(state: string | undefined): { label: string; variant: "default" | "secondary" | "destructive" | "outline" } {
  const s = (state ?? "").toUpperCase();
  if (s === "ORDER_COMPLETED") return { label: "Hoàn tất", variant: "secondary" };
  if (s === "ORDER_CANCELLED" || s === "ORDER_REJECTED" || s === "ORDER_EXPIRED")
    return { label: "Đã hủy", variant: "destructive" };
  if (s === "ORDER_READY") return { label: "Sẵn sàng", variant: "outline" };
  if (s === "ORDER_IN_PREPARE" || s === "ORDER_PREPARING")
    return { label: "Đang chuẩn bị", variant: "default" };
  if (s === "ORDER_SCHEDULED") return { label: "Đã lên lịch", variant: "outline" };
  if (!s) return { label: "—", variant: "outline" };
  return { label: s, variant: "outline" };
}

// ── tab buckets ──────────────────────────────────────────────────────────────

type BucketKey = "customers" | "sources" | "orders";

const BUCKETS: ReadonlyArray<{
  key: BucketKey;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  hint: string;
}> = [
  {
    key: "customers",
    label: "Khách hàng",
    icon: User,
    hint: "Chưa có khách hàng nào — đợi cron get đơn trong vài phút tới nhé.",
  },
  {
    key: "sources",
    label: "Nguồn",
    icon: Store,
    hint: "Chưa có mã cửa hàng / chi nhánh nào trong archive.",
  },
  {
    key: "orders",
    label: "Thông tin đơn hàng",
    icon: ClipboardList,
    hint: "Chưa có đơn nào trong archive — cron 30 giây sẽ bắt đầu lưu khi có đơn preparing.",
  },
];

// ── sub-components ──────────────────────────────────────────────────────────

function CustomerCard({ customer }: { customer: CustomerSummary }) {
  const lastVnd = parseVnd(customer.totalDisplay);
  const state = stateBadge(customer.lastState);
  // Same anonymised-block detection as OrderRow — Grab returns
  // name="***" + mobileNumber="" for some cancelled/completed
  // orders (the customer name is sensitive once the order is
  // final). Consistency with the orders tab: the merchant sees
  // the same "Khách ẩn danh" label everywhere, not two different
  // fallback strings ("Khách ẩn danh" on orders, "Khách lẻ
  // (không tên)" on the customer card).
  const isAnonymised = isAnonymisedEater(customer.name, customer.mobileNumber);
  const displayName = isAnonymised
    ? "Khách ẩn danh"
    : customer.name || "Khách lẻ (không tên)";
  const displayPhone = isAnonymised ? "" : customer.mobileNumber;
  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <CardTitle className="text-base">
            <span className="inline-flex items-center gap-2">
              <User className="h-4 w-4 text-(--color-muted-foreground)" />
              <span className={isAnonymised ? "italic text-(--color-muted-foreground)" : undefined}>
                {displayName}
              </span>
            </span>
          </CardTitle>
          <Badge variant={state.variant}>{state.label}</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        {displayPhone && (
          <div className="flex items-center gap-2 text-(--color-muted-foreground)">
            <Phone className="h-3.5 w-3.5" />
            <span>{displayPhone}</span>
          </div>
        )}
        {customer.address && (
          <div className="flex items-start gap-2 text-(--color-muted-foreground)">
            <MapPin className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span className="line-clamp-2">{customer.address}</span>
          </div>
        )}
        <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
          <span className="text-xs text-(--color-muted-foreground)">
            {customer.orderCount} đơn · lần cuối {formatTimestamp(customer.lastOrderAt)}
          </span>
          {lastVnd > 0 && (
            <span className="text-sm font-semibold text-(--color-foreground)">
              {customer.totalDisplay} ₫
            </span>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function SourceCard({ source }: { source: SourceSummary }) {
  // Display priority — what the operator sees at a glance:
  //   1) Address is the primary identifier (per operator request).
  //      A merchant with many branches needs to see WHERE each
  //      branch is, not just its UUID.
  //   2) Region badge sits next to the address so they can spot
  //      which city/province it belongs to without parsing the
  //      Vietnamese district from the comma-separated string.
  //   3) Shop name is a secondary subtitle — useful when two
  //      branches share an address block (rare) or when the
  //      address hasn't been hydrated yet (legacy rows).
  //   4) Fallback: when neither address nor name is present we
  //      show the merchantId UUID so the card is never blank.
  const showAddress = !!source.address;
  const showName = !!source.name && source.name !== (showAddress ? source.address : "");
  const showRegion = !!source.region;
  const showMerchantIdFallback = !showAddress && !source.name;

  return (
    <Card>
      <CardHeader className="pb-3">
        {/* Title row: shop name + region badge */}
        <div className="flex flex-wrap items-start justify-between gap-2">
          <CardTitle className="text-base">
            <span className="inline-flex items-center gap-2">
              <Store className="h-4 w-4 text-(--color-muted-foreground)" />
              {showMerchantIdFallback ? (
                <span className="font-mono text-sm">{source.merchantId}</span>
              ) : (
                source.name || source.address
              )}
            </span>
          </CardTitle>
          {showRegion && (
            <Badge variant="secondary" className="font-medium">
              {source.region}
            </Badge>
          )}
        </div>
        {/* Address (primary location identifier) */}
        {showAddress && source.name && (
          <div className="mt-2 flex items-start gap-1.5 text-xs text-(--color-muted-foreground)">
            <MapPin className="mt-0.5 h-3 w-3 shrink-0" />
            <span className="line-clamp-2">{source.address}</span>
          </div>
        )}
        {/* Shop name as subtitle when address is shown above as the title */}
        {showAddress && showName && (
          <div className="mt-1 flex items-start gap-1.5 text-xs text-(--color-muted-foreground)">
            <Store className="mt-0.5 h-3 w-3 shrink-0" />
            <span className="line-clamp-2">{source.name}</span>
          </div>
        )}
        {/* Address as subtitle when name is the title (no address shown above) */}
        {!showAddress && showName && showMerchantIdFallback === false && (
          <div className="mt-1 flex items-start gap-1.5 text-xs text-(--color-muted-foreground)">
            <MapPin className="mt-0.5 h-3 w-3 shrink-0" />
            <span className="line-clamp-2">—</span>
          </div>
        )}
      </CardHeader>
      <CardContent className="grid grid-cols-2 gap-3 text-sm">
        <div>
          <div className="text-xs text-(--color-muted-foreground)">Số đơn</div>
          <div className="text-xl font-semibold">{source.orderCount}</div>
        </div>
        <div>
          <div className="text-xs text-(--color-muted-foreground)">Khách riêng biệt</div>
          <div className="text-xl font-semibold">{source.distinctCustomers}</div>
        </div>
      </CardContent>
    </Card>
  );
}

function OrderRow({ order }: { order: OrderSummary }) {
  const state = stateBadge(order.state);
  // Grab's per-order detail endpoint anonymises some cancelled /
  // completed orders: name arrives as the literal string "***"
  // and mobileNumber is empty. We detect that via the shared
  // ``isAnonymisedEater`` helper (same as ``CustomerCard``) so
  // the orders + customers tabs agree on the "Khách ẩn danh"
  // label — better than three dots or "Khách lẻ (không tên)"
  // which implies the data was always missing.
  const rawName = order.detail.eater?.name ?? "";
  const rawPhone = order.detail.eater?.mobileNumber ?? "";
  const isAnonymised = isAnonymisedEater(rawName, rawPhone);
  const eaterName = isAnonymised
    ? "Khách ẩn danh"
    : rawName || "Khách lẻ (không tên)";
  const eaterPhone = isAnonymised ? "" : rawPhone;
  const itemCount = order.detail.itemInfo?.count ?? 0;
  const total = order.detail.fare?.totalDisplay || "—";
  const currency = order.detail.fare?.currencySymbol || "₫";
  const items = order.detail.itemInfo?.items ?? [];
  return (
    <div className="grid grid-cols-12 items-center gap-3 rounded-md border border-(--color-border) p-3 text-sm">
      <div className="col-span-12 md:col-span-3">
        <div className="font-medium text-(--color-foreground)">
          {order.displayId || order.orderId}
        </div>
        <div className="text-xs text-(--color-muted-foreground)">{order.orderId}</div>
      </div>
      <div className="col-span-12 md:col-span-4">
        <div className="flex items-center gap-1.5">
          <User className="h-3.5 w-3.5 text-(--color-muted-foreground)" />
          <span className={isAnonymised ? "italic text-(--color-muted-foreground)" : undefined}>
            {eaterName}
          </span>
        </div>
        {eaterPhone && (
          <div className="flex items-center gap-1.5 text-xs text-(--color-muted-foreground)">
            <Phone className="h-3 w-3" />
            <span>{eaterPhone}</span>
          </div>
        )}
      </div>
      <div className="col-span-6 md:col-span-2">
        <div className="text-xs text-(--color-muted-foreground)">Món</div>
        <div className="font-medium">{itemCount}</div>
      </div>
      <div className="col-span-6 md:col-span-2">
        <div className="text-xs text-(--color-muted-foreground)">Tổng</div>
        <div className="font-medium">
          {total} {currency}
        </div>
      </div>
      <div className="col-span-12 flex flex-wrap items-center justify-between gap-2 md:col-span-1 md:justify-end">
        <Badge variant={state.variant}>{state.label}</Badge>
      </div>
      <div className="col-span-12 flex flex-wrap items-center gap-3 text-xs text-(--color-muted-foreground)">
        <span className="inline-flex items-center gap-1">
          <Clock className="h-3 w-3" />
          Lần cuối: {formatTimestamp(order.lastSeenAt)}
        </span>
        <span className="inline-flex items-center gap-1">
          <Hourglass className="h-3 w-3" />
          Lưu lúc: {formatTimestamp(order.firstSeenAt)}
        </span>
      </div>
      {/* Items list — mirrors the orders-page modal so the merchant
          sees what was actually ordered (e.g. "Phở bò ×1 — 65.000 ₫")
          instead of just the count. Empty → dashed fallback. */}
      {items.length === 0 ? (
        <div className="col-span-12 rounded border border-dashed border-(--color-border) px-3 py-2 text-xs italic text-(--color-muted-foreground)">
          Đơn chưa có món nào.
        </div>
      ) : (
        <ul className="col-span-12 space-y-0.5 border-t border-(--color-border) pt-2">
          {items.map((item, idx) => (
            <OrderItemLine
              key={item.itemID || `${item.name}-${idx}`}
              item={item}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

/** One line-item row under an ``OrderRow``. Mirrors the orders-page
 *  modal style: name + qty on the left, locale price on the right. */
function OrderItemLine({ item }: { item: OrderItem }) {
  const linePrice = parseVnd(item.priceDisplay);
  return (
    <li className="flex items-baseline justify-between gap-2 text-xs">
      <span className="min-w-0 truncate">
        <span className="font-medium text-(--color-foreground)">
          {item.name || "Món không tên"}
        </span>
        <span className="text-(--color-muted-foreground)"> ×{item.quantity}</span>
      </span>
      <span className="shrink-0 font-mono text-[11px] text-(--color-muted-foreground)">
        {formatVnd(linePrice)}
      </span>
    </li>
  );
}

// ── main component ──────────────────────────────────────────────────────────

export function CustomersClient() {
  const [activeBucket, setActiveBucket] = React.useState<BucketKey>("customers");
  const { data, isLoading, isError, error, refetch, isRefetching } =
    useCustomersOverview();

  const customers = data?.customers ?? [];
  const sources = data?.sources ?? [];
  const orders = data?.orders ?? [];

  const activeBucketMeta = BUCKETS.find((b) => b.key === activeBucket) ?? BUCKETS[0];

  return (
    <div className="space-y-4">
      {/* Header banner — mirrors the orders-page "đã chạy get lại đơn" copy */}
      <Card>
        <CardContent className="flex flex-wrap items-center justify-between gap-3 py-3">
          <div className="text-sm text-(--color-muted-foreground)">
            Toàn bộ đơn hàng mà cron 30 giây đã get sẽ được lưu tại đây kèm theo trạng thái của đơn hàng.
          </div>
          <div className="inline-flex items-center gap-3">
            {isRefetching && (
              <span className="inline-flex items-center gap-1.5 text-xs text-(--color-muted-foreground)">
                <Loader2 className="h-3 w-3 animate-spin" />
                Đang đồng bộ…
              </span>
            )}
            <button
              type="button"
              onClick={() => refetch()}
              disabled={isRefetching}
              className="inline-flex items-center gap-1.5 rounded-md bg-(--color-surface-2) px-3 py-1.5 text-sm font-medium text-(--color-foreground) hover:bg-(--color-surface-3, --color-surface-2) disabled:opacity-60"
            >
              <ReceiptText className="h-3.5 w-3.5" />
              Tải lại
            </button>
          </div>
        </CardContent>
      </Card>

      {/* Tabs — custom button pattern (same as orders-client.tsx) */}
      <div className="flex flex-wrap gap-2 border-b border-(--color-border) pb-2">
        {BUCKETS.map((b) => {
          const Icon = b.icon;
          const isActive = b.key === activeBucket;
          const count =
            b.key === "customers"
              ? customers.length
              : b.key === "sources"
                ? sources.length
                : orders.length;
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

      {/* Loading state */}
      {isLoading && (
        <div className="space-y-2">
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
        </div>
      )}

      {/* Error state */}
      {!isLoading && isError && (
        <div className="rounded-md border border-(--color-destructive) bg-(--color-destructive)/10 p-4 text-sm text-(--color-destructive)">
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4" />
            <span>Không tải được dữ liệu khách hàng / nguồn.</span>
          </div>
          <div className="mt-1 text-xs">
            {error instanceof Error ? error.message : "Lỗi không xác định."}
          </div>
        </div>
      )}

      {/* Customers tab */}
      {!isLoading && !isError && activeBucket === "customers" && (
        <>
          {customers.length === 0 ? (
            <div className="rounded-md border border-dashed border-(--color-border) p-6 text-center text-sm text-(--color-muted-foreground)">
              {activeBucketMeta.hint}
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
              {customers.map((c) => (
                <CustomerCard
                  key={c.mobileNumber || `empty-${Math.random()}`}
                  customer={c}
                />
              ))}
            </div>
          )}
        </>
      )}

      {/* Sources tab */}
      {!isLoading && !isError && activeBucket === "sources" && (
        <>
          {sources.length === 0 ? (
            <div className="rounded-md border border-dashed border-(--color-border) p-6 text-center text-sm text-(--color-muted-foreground)">
              {activeBucketMeta.hint}
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
              {sources.map((s) => (
                <SourceCard key={s.merchantId} source={s} />
              ))}
            </div>
          )}
        </>
      )}

      {/* Orders tab */}
      {!isLoading && !isError && activeBucket === "orders" && (
        <>
          {orders.length === 0 ? (
            <div className="rounded-md border border-dashed border-(--color-border) p-6 text-center text-sm text-(--color-muted-foreground)">
              {activeBucketMeta.hint}
            </div>
          ) : (
            <div className="space-y-2">
              {orders.map((o) => (
                <OrderRow key={o.orderId} order={o} />
              ))}
            </div>
          )}
        </>
      )}

      {/* Footer hint — same chrome as orders-client */}
      <div className="text-xs text-(--color-muted-foreground)">
        {isLoading ? (
          <span className="inline-flex items-center gap-1.5">
            <Loader2 className="h-3 w-3 animate-spin" />
            Đang tải…
          </span>
        ) : (
          <span>
            Tổng {customers.length} khách · {sources.length} nguồn · {orders.length} đơn
            đã được get.
          </span>
        )}
      </div>
    </div>
  );
}
