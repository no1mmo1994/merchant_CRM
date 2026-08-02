"use client";

import * as React from "react";
import { Award, Star, AlertCircle } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import Link from "next/link";
import { useUIStore } from "@/lib/stores/ui-store";
import { useAuthStore } from "@/lib/stores/auth-store";
import { useStoreInfo, useStores } from "@/lib/api/stores";
import { useStoreConnectionStatus } from "@/hooks/useStoreConnectionStatus";
import { fadeUp } from "@/lib/animations/variants";
import { motion } from "framer-motion";

/**
 * Scorecard tile — renders the active store's Grab scorecard (rating
 * title + tier + numeric score). Wired to
 * `GET /api/stores/{merchant_id}/info` via `useStoreInfo`. The full
 * payload is fetched so we can also surface scoreRank / desc when
 * Grab provides them.
 *
 * Shown at the top of the dashboard grid, above the placeholder KPIs.
 *
 * Bug fix: when the backend reports `ok=false` for the scorecard
 * section (typical: 401/403 because the auth token is dead), we now
 * inline a "Lỗi AuthToken" banner pointing to /settings, instead of
 * silently rendering three "—" placeholders (which is what the user
 * reported and is exactly why "chưa giải quyết được lấy các thông số
 * đánh giá cửa hàng").
 */
export function ScorecardCard() {
  const activeStoreId = useUIStore((s) => s.activeStoreId);
  const authStores = useAuthStore((s) => s.stores);
  const { data: storesData } = useStores();
  const stores = storesData ?? authStores;
  const activeStore = stores.find((s) => String(s.id) === activeStoreId) ?? stores[0];
  const merchantId = activeStore?.merchant_id ?? null;

  const { data, isLoading, isError } = useStoreInfo(merchantId);
  const { status: connectionStatus } = useStoreConnectionStatus();
  const section = data?.scorecard;
  const raw = section?.data;

  const tokenIsDead =
    isError ||
    connectionStatus === "authtoken_error" ||
    (section && section.ok === false && (section.error ?? "").length > 0);

  return (
    <motion.div
      variants={fadeUp}
      className="lg:col-span-12"
    >
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
            Hạng + điểm đánh giá thời gian thực từ endpoint{" "}
            <span className="font-mono">scorecard</span> của Grab.
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
                  Không thể tải bảng đánh giá từ Grab do auth token không còn hiệu lực. Vui lòng làm mới token tại trang Cài đặt.
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

          {merchantId && !tokenIsDead && data && !activeStore && (
            <div className="text-sm text-(--color-muted-foreground)">
              Chưa chọn cửa hàng — vui lòng chọn một cửa hàng từ thanh trên cùng.
            </div>
          )}

          {merchantId && !tokenIsDead && raw && (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <Stat
                icon={<Star className="h-4 w-4" />}
                label="Điểm"
                value={
                  typeof raw.score === "number"
                    ? `${raw.score.toFixed(1)} / 5`
                    : raw.score ?? "—"
                }
              />
              <Stat
                icon={<Award className="h-4 w-4" />}
                label="Hạng"
                value={raw.scoreRank ?? "—"}
              />
              <Stat
                icon={<Award className="h-4 w-4" />}
                label="Danh hiệu"
                value={raw.title ?? "—"}
              />
              {raw.desc && (
                <div className="col-span-full rounded-md border border-dashed border-(--color-border) p-3 text-sm text-(--color-muted-foreground)">
                  {raw.desc}
                </div>
              )}
            </div>
          )}
          {merchantId && !tokenIsDead && raw === null && section?.error && !tokenIsDead && (
            <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-2 text-xs text-amber-600 dark:text-amber-400">
              Grab không trả về bảng đánh giá: {section.error}
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
}: {
  icon: React.ReactNode;
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-(--color-border) bg-(--color-surface-2) p-3">
      <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-(--color-muted-foreground)">
        {icon}
        {label}
      </div>
      <div className="mt-1 text-lg font-semibold text-(--color-foreground)">{value}</div>
    </div>
  );
}
