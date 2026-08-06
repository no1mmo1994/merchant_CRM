import { PageHeader } from "@/components/layout/page-header";
import { OrdersClient } from "./orders-client";

/**
 * /orders — Đơn hàng page.
 *
 * Server-component shell that hands off to the client component
 * (mirrors the /finance and /stores pattern). The client owns the
 * TanStack Query fetch + UI rendering for the preparing-order queue.
 */
export default function OrdersPage() {
  return (
    <div className="space-y-6 p-6">
      <PageHeader
        title="Đơn hàng"
        description="Danh sách đơn hàng đang chuẩn bị — đồng bộ trực tiếp từ Grab Merchant."
      />
      <OrdersClient />
    </div>
  );
}
