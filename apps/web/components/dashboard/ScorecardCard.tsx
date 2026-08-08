"use client";

import * as React from "react";
import { Award, Star, AlertCircle, BadgeCheck } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import Link from "next/link";
import { useUIStore } from "@/lib/stores/ui-store";
import { useAuthStore } from "@/lib/stores/auth-store";
import { useStores } from "@/lib/api/stores";
import { useGoldenApronSummary } from "@/lib/api/golden-apron";
import { useStoreConnectionStatus } from "@/hooks/useStoreConnectionStatus";
import { fadeUp } from "@/lib/animations/variants";
import { motion } from "framer-motion";
import { cn } from "@/lib/utils";

/**
 * Store standing at the top of the dashboard: stars, tier, apron title.
 *
 * Reads `GET /api/golden-apron/summary`, not Grab's `scorecard` endpoint.
 * That endpoint's `score` is store-profile completeness out of 100 — its
 * own `desc` is about having the information customers look for, and it
 * sets `shouldShowScore: false`. This card used to render it as
 * "100.0 / 5", which is wrong twice over: wrong scale, and not a rating
 * at all. The star rating lives in the feedback service; the tier lives
 * in the tier page.
 *
 * The apron title is derived from the current tier server-side, so it
 * follows a promotion on the next refetch rather than being stored
 * anywhere that could go stale.
 */

/** Tier tints, warmest at the top of the ladder — matches /golden-apron. */
const TIER_TONE: Record<string, string> = {
  "Cơ Bản": "text-(--color-muted-foreground)",
  Bạc: "text-slate-400",
  Vàng: "text-amber-500",
};

export function ScorecardCard() {
  const activeStoreId = useUIStore((s) => s.activeStoreId);
  const authStores = useAuthStore((s) => s.stores);
  const { data: storesData } = useStores();
  const stores = storesData ?? authStores;
  const activeStore = stores.find((s) => String(s.id) === activeStoreId) ?? stores[0];
  const merchantId = activeStore?.merchant_id ?? null;

  const { data, isLoading, isError, error } = useGoldenApronSummary(merchantId);
  const { status: connectionStatus } = useStoreConnectionStatus();

  // Only `useStoreConnectionStatus` gets to call a token dead — it debounces
  // over consecutive failures for exactly that purpose. This query can't:
  // the backend maps every Grab failure (500, 503, 429, timeout) to a 502,
  // so keying the banner off `isError` would tell the operator to go and
  // refresh a perfectly good token because Grab hiccuped twice.
  const tokenIsDead = connectionStatus === "authtoken_error";
  const loadFailed = isError && !tokenIsDead;
  const tierTone = TIER_TONE[data?.currentTier ?? ""] ?? "text-(--color-brand)";

  return (
    <motion.div variants={fadeUp} className="lg:col-span-12">
      <Card className="border-(--color-border)">
        <CardHeader>
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <Award className="h-4 w-4 text-(--color-brand)" />
              <CardTitle>Bảng đánh giá cửa hàng</CardTitle>
            </div>
            {activeStore && (
              <span className="font-mono text-xs text-(--color-muted-foreground)">
                {activeStore.merchant_id}
              </span>
            )}
          </div>
          <CardDescription>
            Số sao, hạng và danh hiệu Tạp Dề — cập nhật theo dữ liệu Grab.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {!merchantId && (
            <div className="rounded-lg border border-dashed border-(--color-border) p-4 text-sm text-(--color-muted-foreground)">
              Chưa có cửa hàng nào được kết nối.
            </div>
          )}

          {merchantId && isLoading && (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} className="h-16" />
              ))}
            </div>
          )}

          {merchantId && tokenIsDead && (
            <div className="flex items-start gap-3 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3">
              <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-amber-600 dark:text-amber-400" />
              <div className="min-w-0 flex-1 space-y-1.5 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold text-amber-700 dark:text-amber-300">
                    Lỗi AuthToken
                  </span>
                  <Badge variant="outline" className="border-amber-500/50 text-amber-700 dark:text-amber-300">
                    Token hết hạn / không hợp lệ
                  </Badge>
                </div>
                <p className="text-amber-700/90 dark:text-amber-200/80">
                  Không thể tải bảng đánh giá từ Grab do auth token không còn
                  hiệu lực. Vui lòng làm mới token tại trang Cài đặt.
                </p>
                <Link
                  href="/settings"
                  className="inline-flex items-center gap-1 rounded-md border border-amber-500/50 bg-amber-500/20 px-3 py-1 text-xs font-medium text-amber-800 hover:bg-amber-500/30 dark:text-amber-200"
                >
                  Đi tới Cài đặt để làm mới token
                </Link>
              </div>
            </div>
          )}

          {merchantId && loadFailed && (
            <div className="rounded-lg border border-(--color-border) bg-(--color-surface-2) p-3 text-sm text-(--color-muted-foreground)">
              {error instanceof Error
                ? error.message
                : "Không tải được bảng đánh giá từ Grab. Thử lại sau ít phút."}
            </div>
          )}

          {merchantId && !tokenIsDead && !loadFailed && data && (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <Stat
                icon={<Star className="h-4 w-4" />}
                label="Số sao đánh giá"
                value={data.rating === null ? "—" : `${data.rating.toFixed(1)} / 5`}
                hint={
                  data.ratingCount === null
                    ? undefined
                    : `${data.ratingCount} lượt đánh giá`
                }
              />
              <Stat
                icon={<Award className="h-4 w-4" />}
                label="Hạng"
                value={data.currentTier || "—"}
                valueClassName={tierTone}
                hint={
                  data.totalCount > 0
                    ? `Đạt ${data.achievedCount}/${data.totalCount} điều kiện`
                    : undefined
                }
              />
              <Stat
                icon={<BadgeCheck className="h-4 w-4" />}
                label="Danh hiệu"
                // Empty when Grab didn't state a tier — a title invented
                // over a blank tier would claim a standing nothing backs.
                value={data.apronTitle || "—"}
                valueClassName={tierTone}
                hint={
                  <Link href="/golden-apron" className="hover:underline">
                    Xem điều kiện lên hạng →
                  </Link>
                }
              />

              {data.profileDesc && (
                <div className="col-span-full rounded-md border border-dashed border-(--color-border) p-3 text-sm text-(--color-muted-foreground)">
                  {data.profileDesc}
                  {data.profileScore !== null && (
                    <>
                      {" "}
                      <span className="font-mono text-xs">
                        (điểm hoàn thiện thông tin: {data.profileScore}/100)
                      </span>
                    </>
                  )}
                </div>
              )}

              {data.warnings.length > 0 && (
                <div className="col-span-full rounded-md border border-amber-500/30 bg-amber-500/5 p-2 text-xs text-amber-600 dark:text-amber-400">
                  {data.warnings.join(" ")}
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </motion.div>
  );
}

function Stat({
  icon,
  label,
  value,
  hint,
  valueClassName,
}: {
  icon: React.ReactNode;
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  valueClassName?: string;
}) {
  return (
    <div className="rounded-lg border border-(--color-border) bg-(--color-surface-2) p-3">
      <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-(--color-muted-foreground)">
        {icon}
        {label}
      </div>
      <div className={cn("mt-1 text-lg font-semibold text-(--color-foreground)", valueClassName)}>
        {value}
      </div>
      {hint && (
        <div className="mt-0.5 text-xs text-(--color-muted-foreground)">{hint}</div>
      )}
    </div>
  );
}
