"use client";

import * as React from "react";
import { Activity, AlertCircle, Circle, Loader2 } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useUIStore } from "@/lib/stores/ui-store";
import { useAuthStore } from "@/lib/stores/auth-store";
import { useStoreStatus, useStores } from "@/lib/api/stores";
import {
  type StoreConnectionStatus,
  useStoreConnectionStatus,
} from "@/hooks/useStoreConnectionStatus";
import { fadeUp } from "@/lib/animations/variants";
import { motion } from "framer-motion";
import Link from "next/link";

const STATUS_VARIANTS: Record<string, "default" | "destructive" | "secondary" | "outline"> = {
  ACTIVE: "default",
  PENDING: "secondary",
  SUSPENDED: "destructive",
  INACTIVE: "secondary",
};

const STATUS_LABELS: Record<string, string> = {
  ACTIVE: "Đang hoạt động",
  PENDING: "Đang chờ duyệt",
  SUSPENDED: "Bị đình chỉ",
  INACTIVE: "Không hoạt động",
};

/**
 * Live store account status card — mirrors the
 * `trangchu/get_trangthai_hoatdong.py` logic.
 *
 * Three-state UI:
 *  - ACTIVE       → pulsing green dot, "Đang hoạt động"
 *  - PENDING/...  → coloured dot, mapped Vietnamese label
 *  - authtoken_error → amber alert, prominent "Lỗi AuthToken" banner
 *                     that links to Settings so the user can refresh.
 */
export function StoreStatusCard() {
  const activeStoreId = useUIStore((s) => s.activeStoreId);
  const authStores = useAuthStore((s) => s.stores);
  const { data: storesData } = useStores();
  const stores = storesData ?? authStores;
  const activeStore = stores.find((s) => String(s.id) === activeStoreId) ?? stores[0];
  const merchantId = activeStore?.merchant_id ?? null;

  const { data, isLoading, isError, error } = useStoreStatus(merchantId);
  const { status } = useStoreConnectionStatus();

  return (
    <motion.div variants={fadeUp} className="lg:col-span-12">
      <Card className="border-(--color-border)">
        <CardHeader>
          <div className="flex items-center gap-2">
            <Activity className="h-4 w-4 text-(--color-brand)" />
            <CardTitle>Trạng thái cửa hàng</CardTitle>
          </div>
          <CardDescription>
            Trạng thái trực tiếp từ endpoint{" "}
            <span className="font-mono">store-list</span> của Grab. Cập nhật tự động mỗi 30 giây.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {!merchantId && (
            <div className="rounded-lg border border-dashed border-(--color-border) p-4 text-sm text-(--color-muted-foreground)">
              Chưa có cửa hàng nào được kết nối. Vui lòng đăng nhập để bắt đầu.
            </div>
          )}

          {merchantId && isLoading && (
            <Skeleton className="h-14 w-full" />
          )}

          {/* Auth-token error takes precedence — it's the most useful
              signal for the user even when the underlying data fetch
              also fails. */}
          {merchantId && status === "authtoken_error" && (
            <AuthTokenErrorBlock error={error} />
          )}

          {merchantId && status !== "authtoken_error" && isError && (
            <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-3 text-sm text-red-500">
              Không thể kết nối tới Grab ngay lúc này. Vui lòng thử lại sau ít phút.
            </div>
          )}

          {data && !activeStore && (
            <div className="text-sm text-(--color-muted-foreground)">
              Chưa chọn cửa hàng.
            </div>
          )}

          {data?.ok && status !== "authtoken_error" && (
            <div className="flex flex-wrap items-center gap-4">
              <div className="flex items-center gap-2">
                {data.status === "ACTIVE" && (
                  <span className="relative flex h-3 w-3">
                    <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-green-400 opacity-75" />
                    <span className="relative inline-flex h-3 w-3 rounded-full bg-green-500" />
                  </span>
                )}
                {data.status !== "ACTIVE" && (
                  <Circle className="h-3 w-3 fill-current" />
                )}
                <Badge variant={STATUS_VARIANTS[data.status ?? "default"] ?? "secondary"}>
                  {STATUS_LABELS[data.status ?? ""] ?? data.status ?? "—"}
                </Badge>
              </div>
              {data.status_display && (
                <span className="text-sm text-(--color-muted-foreground)">
                  {data.status_display}
                </span>
              )}
              {data.pending === true && (
                <Badge variant="secondary" className="border-amber-500/50 text-amber-600 dark:text-amber-400">
                  Đang chờ Grab duyệt
                </Badge>
              )}
              {data.error && (
                <span className="text-xs text-amber-500">
                  Dữ liệu một phần: {data.error}
                </span>
              )}
            </div>
          )}

          {data?.ok && !data.status && (
            <div className="text-sm text-(--color-muted-foreground)">
              Grab không trả về trạng thái cho cửa hàng này.
            </div>
          )}
        </CardContent>
      </Card>
    </motion.div>
  );
}

function AuthTokenErrorBlock({ error }: { error: unknown }) {
  const errStatus =
    error && typeof error === "object" && "status" in error
      ? (error as { status?: number }).status
      : undefined;
  const isAuth = errStatus === 401 || errStatus === 403;
  return (
    <div className="flex items-start gap-3 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3">
      <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-amber-600 dark:text-amber-400" />
      <div className="min-w-0 flex-1 space-y-2 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-semibold text-amber-700 dark:text-amber-300">
            Lỗi AuthToken
          </span>
          <Badge variant="outline" className="border-amber-500/50 text-amber-700 dark:text-amber-300">
            Token hết hạn / không hợp lệ
          </Badge>
        </div>
        <p className="text-amber-700/90 dark:text-amber-200/80">
          {isAuth
            ? "Grab từ chối xác thực do auth token đã hết hạn hoặc không hợp lệ."
            : "Hệ thống không thể kết nối tới Grab sau nhiều lần thử. Token cục bộ có thể đã hết hạn."}
          {" "}
          Vui lòng làm mới token tại trang Cài đặt để tiếp tục sử dụng.
        </p>
        <div>
          <Link
            href="/settings"
            className="inline-flex items-center gap-1 rounded-md border border-amber-500/50 bg-amber-500/20 px-3 py-1 text-xs font-medium text-amber-800 hover:bg-amber-500/30 dark:text-amber-200"
          >
            Đi tới Cài đặt để làm mới token
          </Link>
        </div>
      </div>
    </div>
  );
}

export type { StoreConnectionStatus };
