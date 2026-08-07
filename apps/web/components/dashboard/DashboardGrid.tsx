"use client";

import { motion } from "framer-motion";
import { type LucideIcon } from "lucide-react";
import { SalesPerformanceChart } from "./SalesPerformanceChart";
import { VisitorsChart } from "./VisitorsChart";
import { OrdersTable } from "./OrdersTable";
import { ScorecardCard } from "./ScorecardCard";
import { StoreStatusCard } from "./StoreStatusCard";
import { StoreHoursCard } from "./StoreHoursCard";
import { FinancialReportCard } from "./FinancialReportCard";
import { EmptyState } from "@/components/feedback/EmptyState";
import { Card, CardContent } from "@/components/ui/card";
import { staggerContainer } from "@/lib/animations/variants";
import { useUIStore } from "@/lib/stores/ui-store";
import { useAuthStore } from "@/lib/stores/auth-store";
import { useStores } from "@/lib/api/stores";

/**
 * Dashboard grid (Round 8 — financial report).
 *
 * The 4 placeholder `StatCard` tiles ("Doanh thu / Trung bình ngày /
 * Khách hàng mới / Tổng đơn hàng" — all "—" with footer "Chưa có
 * endpoint KPI từ backend") have been replaced by a single integrated
 * ``FinancialReportCard`` that pulls the same ``/api/finance/summary``
 * data the /finance page uses.
 *
 * Layout, top-to-bottom:
 *   1. ScorecardCard        (real: today's scorecard)
 *   2. StoreStatusCard      (real: realtime runtime state)
 *   3. StoreHoursCard       (real: weekly schedule)
 *   4. FinancialReportCard  (real: Tổng đơn / Doanh thu /
 *      Chiết khấu / VAT / Số tiền thực nhận + breakdown %)
 *   5. SalesPerformanceChart (placeholder shell — no daily series yet)
 *   6. VisitorsChart        (placeholder shell — no visitor source yet)
 *   7. OrdersTable          (real: latest archived orders)
 *
 * The chart shells stay because the operator already uses them as
 * layout anchors — they render an honest empty state instead of fake
 * numbers. Removing them entirely would shift the grid in ways that
 * surprise the operator.
 */
export function DashboardGrid() {
  const activeStoreId = useUIStore((s) => s.activeStoreId);
  const authStores = useAuthStore((s) => s.stores);
  const { data: storesData } = useStores();
  const stores = storesData ?? authStores;
  const activeStore = stores.find((s) => String(s.id) === activeStoreId) ?? stores[0];

  const hasStore = !!activeStore;

  return (
    <motion.div
      variants={staggerContainer}
      initial="hidden"
      animate="show"
      className="grid grid-cols-12 gap-6"
    >
      <ScorecardCard />
      {/* Realtime runtime state (Open / BusyMode / Paused) + the
          "Đặt trạng thái quán" trigger — single-purpose panel. */}
      <StoreStatusCard />
      {/* 7-day operating-hours table — mirrors `cuahang/trangthai.py`.
          Pairs with StoreStatusCard above:
            - StoreStatusCard: realtime runtime state (Open / Busy /
              Paused) + the trigger button to change it
            - StoreHoursCard:   the weekly schedule from
              /food/merchant/v2/merchants (read-only) */}
      {hasStore && <StoreHoursCard />}

      {!hasStore ? (
        <NoStoreBanner />
      ) : (
        <>
          {/* Real financial report — replaces the four "—" tiles. */}
          <FinancialReportCard />

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

// Re-export the icon type so consumers get autocomplete. (Unused at
// runtime — only here so `import { type LucideIcon }` doesn't strip
// tree-shaking warnings.)
export type { LucideIcon };
