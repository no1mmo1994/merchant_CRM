"use client";

import * as React from "react";
import { Clock } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useStores, useStoreOpeningHours } from "@/lib/api/stores";
import { useAuthStore } from "@/lib/stores/auth-store";
import { useUIStore } from "@/lib/stores/ui-store";
import { cn } from "@/lib/utils";
import { fadeUp } from "@/lib/animations/variants";
import { motion } from "framer-motion";

/**
 * Vietnamese day labels — order matches Grab's `openingHours` array
 * (0 = Thứ Hai … 6 = Chủ Nhật), exactly mirroring the index order
 * `cuahang/trangthai.py` uses.
 */
const DAY_LABELS_VI = [
  "Thứ Hai",
  "Thứ Ba",
  "Thứ Tư",
  "Thứ Năm",
  "Thứ Sáu",
  "Thứ Bảt",
  "Chủ Nhật",
] as const;

interface StoreHoursCardProps {
  /** Optional — when omitted the card resolves the active store itself. */
  merchantId?: string | null;
}

/**
 * Weekly opening-hours table for the active store.
 *
 * Mirrors `cuahang/trangthai.py` which calls
 * `GET https://api.grab.com/food/merchant/v2/merchants`. The runtime
 * state (Open / Busy / Paused) lives on `StoreStatusCard` together
 * with the account-level state — this card is purely a schedule view
 * so a merchant can see their weekly operating hours at a glance.
 *
 * The card is read-only; mutations go through `StoreStatusDialog`
 * (BUSY / TEMPPAUSED) on `StoreStatusCard`.
 */
export function StoreHoursCard({ merchantId: merchantIdProp }: StoreHoursCardProps = {}) {
  const activeStoreId = useUIStore((s) => s.activeStoreId);
  const authStores = useAuthStore((s) => s.stores);
  const { data: storesData } = useStores();
  const stores = storesData ?? authStores;
  const activeStore = stores.find((s) => String(s.id) === activeStoreId) ?? stores[0];
  const merchantId = merchantIdProp ?? activeStore?.merchant_id ?? null;

  const { data, isLoading, isError, error } = useStoreOpeningHours(merchantId);

  // Decide which day's row to highlight as "today" (Grab's index
  // convention is 0 = Monday … 6 = Sunday, but JS `getDay()` is
  // 0 = Sunday … 6 = Saturday — translate accordingly).
  const todayIndex = React.useMemo(() => {
    const js = new Date().getDay(); // 0=Sun..6=Sat
    return js === 0 ? 6 : js - 1; // → 0=Mon..6=Sun
  }, []);

  return (
    <motion.div variants={fadeUp} className="lg:col-span-12">
      <Card className="border-(--color-border)">
        <CardHeader>
          <div className="space-y-1.5">
            <div className="flex items-center gap-2">
              <Clock className="h-4 w-4 text-(--color-brand)" />
              <CardTitle>Giờ hoạt động cửa hàng</CardTitle>
            </div>
            <CardDescription>
              Lịch hoạt động trong tuần từ{" "}
              <span className="font-mono">/food/merchant/v2/merchants</span>{" "}
              của Grab. Trạng thái realtime (Mở cửa / Bận / Tạm nghỉ)
              hiển thị ở thẻ <strong>Trạng thái cửa hàng</strong> phía
              trên.
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          {!merchantId ? (
            <div className="rounded-lg border border-dashed border-(--color-border) p-4 text-sm text-(--color-muted-foreground)">
              Chưa có cửa hàng nào được kết nối.
            </div>
          ) : isLoading ? (
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
              {[0, 1, 2, 3, 4, 5, 6].map((i) => (
                <Skeleton key={i} className="h-10" />
              ))}
            </div>
          ) : isError ? (
            <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-3 text-sm text-red-500">
              Không thể kết nối tới Grab ngay lúc này.
              {error instanceof Error ? ` (${error.message})` : null}
            </div>
          ) : (data?.data.opening_hours.length ?? 0) === 0 ? (
            <div className="rounded-lg border border-dashed border-(--color-border) p-4 text-sm text-(--color-muted-foreground)">
              Grab không trả về lịch hoạt động cho cửa hàng này.
            </div>
          ) : (
            <ul className="divide-y divide-(--color-border) rounded-lg border border-(--color-border)">
              {data!.data.opening_hours.map((day) => {
                const isToday = day.day_index === todayIndex;
                const label = DAY_LABELS_VI[day.day_index] ?? `Ngày ${day.day_index + 1}`;
                return (
                  <li
                    key={day.day_index}
                    className={cn(
                      "flex items-center gap-3 px-3 py-2 text-sm transition",
                      isToday && "bg-(--color-brand)/5 font-medium",
                    )}
                  >
                    <span
                      className={cn(
                        "w-24 shrink-0",
                        isToday
                          ? "text-(--color-brand)"
                          : "text-(--color-muted-foreground)",
                      )}
                    >
                      {label}
                      {isToday && (
                        <span className="ml-1 rounded bg-(--color-brand)/15 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-(--color-brand)">
                          hôm nay
                        </span>
                      )}
                    </span>
                    {day.ranges.length === 0 ? (
                      <span className="text-xs italic text-(--color-muted-foreground)">
                        Nghỉ (không có giờ hoạt động)
                      </span>
                    ) : (
                      <span className="flex flex-wrap gap-x-3 gap-y-1">
                        {day.ranges.map((r, i) => (
                          <span
                            key={`${day.day_index}-${i}`}
                            className="font-mono tabular-nums text-(--color-foreground)"
                          >
                            {formatRange(r.start, r.end)}
                          </span>
                        ))}
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </CardContent>
      </Card>
    </motion.div>
  );
}

function formatRange(start: string, end: string): string {
  if (!start && !end) return "—";
  return `${start || "?"} – ${end || "?"}`;
}

// Re-export the day labels so other modules (e.g. tests, future
// schedule pickers) can reuse the same canonical Vietnamese ordering.
export { DAY_LABELS_VI };