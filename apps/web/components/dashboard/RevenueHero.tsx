"use client";

import { motion } from "framer-motion";
import { Card, CardContent } from "@/components/ui/card";
import { FilterToolbar } from "./FilterToolbar";
import { fadeUp } from "@/lib/animations/variants";
import { formatPercent, formatVND } from "@/lib/data/placeholder-kpis";
import { TrendingUp } from "lucide-react";

interface RevenueHeroProps {
  /**
   * Pass `null` to render an honest empty state (this is the new
   * default — the old v1 rendered hard-coded fake numbers here).
   * Pass a number once the backend exposes a real revenue KPI.
   */
  revenue: number | null;
  change: number | null;
  /** Set true when there's no data to show. */
  isEmpty?: boolean;
  /** Show skeleton-style "…" while the real KPI fetch is in flight. */
  loading?: boolean;
  /** Decorative store name — only used in the empty-state copy. */
  storeName?: string | null;
}

/**
 * Revenue hero card. v1 rendered `placeholderKPIs.totalRevenue`
 * (858 198.46 VND) — that was fake data the user explicitly asked
 * us to remove (issue #6). Now:
 *  - If `revenue` is a number, show it formatted as VND.
 *  - Else, render an empty-state hint instead of a fabricated figure.
 */
export function RevenueHero({
  revenue,
  change,
  isEmpty = false,
  loading = false,
  storeName = null,
}: RevenueHeroProps) {
  return (
    <motion.div variants={fadeUp} className="lg:col-span-8">
      <Card className="overflow-hidden border-(--color-border)">
        <CardContent className="space-y-4 p-6">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="text-sm font-medium text-(--color-muted-foreground)">
                Tổng doanh thu
              </div>
              {loading ? (
                <div className="mt-2 h-12 w-44 animate-pulse rounded-md bg-(--color-surface-2)" />
              ) : revenue !== null ? (
                <>
                  <div className="mt-2 text-4xl font-semibold tracking-tight text-(--color-foreground) sm:text-5xl">
                    {formatVND(revenue)}
                  </div>
                  {typeof change === "number" && (
                    <div className="mt-2 inline-flex items-center gap-1.5 text-xs text-(--color-muted-foreground)">
                      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 font-medium text-emerald-600 dark:text-emerald-400">
                        <TrendingUp className="h-3 w-3" />
                        {formatPercent(change)}
                      </span>
                      so với kỳ trước
                    </div>
                  )}
                </>
              ) : (
                <EmptyRevenue storeName={storeName} isEmpty={isEmpty} />
              )}
            </div>
            <FilterToolbar />
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}

function EmptyRevenue({
  storeName,
  isEmpty,
}: {
  storeName: string | null;
  isEmpty: boolean;
}) {
  return (
    <div className="mt-2 space-y-1">
      <div className="text-3xl font-semibold tracking-tight text-(--color-muted-foreground)">
        —
      </div>
      <p className="max-w-md text-xs text-(--color-muted-foreground)">
        {isEmpty
          ? "Token chưa hợp lệ — vui lòng làm mới tại Cài đặt để xem doanh thu."
          : storeName
            ? `Chưa có số liệu doanh thu cho cửa hàng "${storeName}".`
            : "Chưa có số liệu doanh thu. Số liệu sẽ hiển thị khi backend cung cấp KPI."}
      </p>
    </div>
  );
}
