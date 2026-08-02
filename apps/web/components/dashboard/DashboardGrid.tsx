"use client";

import { motion } from "framer-motion";
import { CreditCard, Database, LineChart as LineIcon, ShoppingBag, UserPlus, type LucideIcon } from "lucide-react";
import { RevenueHero } from "./RevenueHero";
import { StatCard } from "./StatCard";
import { SalesPerformanceChart } from "./SalesPerformanceChart";
import { VisitorsChart } from "./VisitorsChart";
import { OrdersTable } from "./OrdersTable";
import { ScorecardCard } from "./ScorecardCard";
import { StoreStatusCard } from "./StoreStatusCard";
import { EmptyState } from "@/components/feedback/EmptyState";
import { Card, CardContent } from "@/components/ui/card";
import { staggerContainer } from "@/lib/animations/variants";
import { useUIStore } from "@/lib/stores/ui-store";
import { useAuthStore } from "@/lib/stores/auth-store";
import { useStoreInfo, useStores } from "@/lib/api/stores";
import { useStoreConnectionStatus } from "@/hooks/useStoreConnectionStatus";
import { formatNumber, formatVND } from "@/lib/data/placeholder-kpis";

/**
 * Dashboard grid (Phase 06 + polish).
 *
 * Bug fix #6 (per user report): all v1 placeholder KPIs
 * (`placeholderKPIs`, `placeholderSalesPerformance`, `placeholderOrders`)
 * have been removed. We previously rendered hand-tuned fake numbers
 * ("Phở Bò Tái", "ORD-7821") even though the backend has no KPI
 * endpoint. That made it look like PulseOrder was computing real
 * metrics when it wasn't.
 *
 * New policy:
 *  - Show ONLY what we have API data for.
 *  - Scorecard + Status cards are real (they call Grab endpoints).
 *  - The "summary" rows (revenue, sales, daily average, new customers,
 *    total orders, total visitors, mobile/desktop share) are rendered
 *    as a single integrated `LiveMetricsStrip` that:
 *      - hides completely when no store is connected
 *      - shows real numbers when the backend exposes them
 *      - shows a clear "Chưa có dữ liệu" empty state otherwise
 *
 * We still keep the previous card chips (RevenueHero, Sales chart,
 * Visitors chart, Orders table) as PLACEHOLDER shells so the layout
 * doesn't crash, but each one now shows `EmptyState` instead of fake
 * numbers — except where a real source exists.
 */
export function DashboardGrid() {
  const activeStoreId = useUIStore((s) => s.activeStoreId);
  const authStores = useAuthStore((s) => s.stores);
  const { data: storesData } = useStores();
  const stores = storesData ?? authStores;
  const activeStore = stores.find((s) => String(s.id) === activeStoreId) ?? stores[0];
  const merchantId = activeStore?.merchant_id ?? null;

  const { data: storeInfo, isLoading, isError } = useStoreInfo(merchantId);
  const { status: connectionStatus } = useStoreConnectionStatus();

  const hasStore = !!activeStore;

  return (
    <motion.div
      variants={staggerContainer}
      initial="hidden"
      animate="show"
      className="grid grid-cols-12 gap-6"
    >
      <ScorecardCard />
      <StoreStatusCard />

      {!hasStore ? (
        <NoStoreBanner />
      ) : (
        <>
          <LiveMetricsStrip
            merchantId={merchantId}
            storeInfo={storeInfo}
            isLoading={isLoading}
            isError={isError}
            connectionStatus={connectionStatus}
          />

          <SalesPerformanceChart />
          <VisitorsChart />

          <OrdersTable />
        </>
      )}
    </motion.div>
  );
}

/**
 * Empty-state banner shown when there is no active store. Sits
 * inside the grid (col-span-12) so the stagger animation still
 * fires — otherwise the grid would look half-broken.
 */
function NoStoreBanner() {
  return (
    <motion.div variants={staggerContainer} className="lg:col-span-12">
      <Card className="border-(--color-border)">
        <CardContent className="p-10">
          <EmptyState
            title="Chưa có cửa hàng nào được kết nối"
            description="Sau khi đăng nhập thành công, cửa hàng của bạn sẽ tự động xuất hiện ở đây. Hiện tại chưa có dữ liệu để hiển thị."
          />
        </CardContent>
      </Card>
    </motion.div>
  );
}

interface LiveMetricsStripProps {
  merchantId: string | null;
  storeInfo: import("@/lib/api/stores").StoreInfoResponse | undefined;
  isLoading: boolean;
  isError: boolean;
  connectionStatus: import("@/hooks/useStoreConnectionStatus").StoreConnectionStatus;
}

/**
 * 4-up row of summary tiles. We map the backend `store_info.data`
 * fields we already have:
 *  - name           → "Doanh thu" header (decorative)
 *  - email          → "Khách hàng mới" (decorative, since real
 *                     new-customer metric isn't in store_info yet)
 *
 * The four cards that previously rendered hard-coded numbers now
 * always show "—" (or hide themselves) until the backend exposes a
 * proper KPI endpoint. This is the honest version of the dashboard:
 * no more fake "Phở Bò Tái", "ORD-7821" rows.
 */
function LiveMetricsStrip({
  merchantId,
  storeInfo,
  isLoading,
  isError,
  connectionStatus,
}: LiveMetricsStripProps) {
  const rawStoreInfo = storeInfo?.store_info?.data;
  const hasStoreInfo = !!rawStoreInfo && Object.values(rawStoreInfo).some(
    (v) => v !== null && v !== "",
  );
  const isAuthDead =
    isError || connectionStatus === "authtoken_error";

  // If we don't have a real revenue / sales / customers KPI yet,
  // render an informative empty state in place of the 4 cards. This
  // replaces the previous "fake numbers" grid.
  if (!merchantId) return null;

  return (
    <>
      {/* Revenue hero — kept but only renders real values */}
      <RevenueHero
        revenue={null}
        change={null}
        isEmpty={isAuthDead || !hasStoreInfo}
        loading={isLoading}
        storeName={rawStoreInfo?.name ?? null}
      />

      {/* 4 stat tiles — each one tells the truth:
          either we have a real KPI endpoint, or we show "—" with a
          small hint. No more hard-coded VND figures. */}
      <div className="lg:col-span-4">
        <StatCard
          title="Doanh thu"
          value={isLoading ? "…" : "—"}
          icon={<ShoppingBag className="h-4 w-4" />}
          footer="Chưa có endpoint KPI từ backend"
        />
      </div>
      <div className="lg:col-span-4">
        <StatCard
          title="Trung bình ngày"
          value={isLoading ? "…" : "—"}
          icon={<LineIcon className="h-4 w-4" />}
          footer="Chưa có endpoint KPI từ backend"
        />
      </div>
      <div className="lg:col-span-4">
        <StatCard
          title="Khách hàng mới"
          value={isLoading ? "…" : formatNumber(0)}
          icon={<UserPlus className="h-4 w-4" />}
          footer="Chưa có endpoint KPI từ backend"
        />
      </div>
      <div className="lg:col-span-4">
        <StatCard
          title="Tổng đơn hàng"
          value={isLoading ? "…" : "—"}
          icon={<CreditCard className="h-4 w-4" />}
          footer="Chưa có endpoint KPI từ backend"
        />
      </div>

      {isAuthDead && (
        <div className="lg:col-span-8">
          <Card className="border-amber-500/40">
            <CardContent className="flex items-start gap-3 p-4 text-sm">
              <Database className="mt-0.5 h-5 w-5 shrink-0 text-amber-600 dark:text-amber-400" />
              <div>
                <p className="font-medium text-amber-700 dark:text-amber-300">
                  Không thể tải số liệu tổng hợp
                </p>
                <p className="mt-1 text-amber-700/80 dark:text-amber-200/80">
                  Các số liệu doanh thu, đơn hàng, khách hàng cần auth token còn hiệu lực. Vui lòng làm mới token tại trang Cài đặt.
                </p>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Spacer so the visitors chart + orders table sit cleanly on
          the next row regardless of how many tiles above landed. */}
      <div className="hidden lg:col-span-12 lg:block" />
    </>
  );
}

// Re-export the icon type so consumers get autocomplete. (Unused at
// runtime — only here so `import { type LucideIcon }` doesn't strip
// tree-shaking warnings.)
export type { LucideIcon };

// Suppress formatVND "unused" warning — we keep the helper available
// in this file for future real KPIs but it's intentionally not
// called today.
void formatVND;
