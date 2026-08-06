import { PageHeader } from "@/components/layout/page-header";
import { CustomersClient } from "./customers-client";

/**
 * /customers — Khách hàng & Nguồn page.
 *
 * Server-component shell that hands off to the client component
 * (mirrors the /orders / /finance pattern). The client owns the
 * TanStack Query fetch + the three-tab UI:
 *   * Khách hàng — distinct customers by phone
 *   * Nguồn — distinct merchant_id (mã cửa hàng / chi nhánh)
 *   * Thông tin đơn hàng — full per-order detail hydrated from
 *                          the archive with the order's state
 *
 * All data is hydrated from the existing `OrderArchive` table
 * (the 30-second cron keeps writing to it). No new tables.
 */
export default function CustomersPage() {
  return (
    <div className="space-y-6 p-6">
      <PageHeader
        title="Khách hàng & Nguồn"
        description="Danh sách khách hàng, nguồn đơn (mã cửa hàng / chi nhánh) và thông tin đơn hàng đã được get — đồng bộ từ OrderArchive."
      />
      <CustomersClient />
    </div>
  );
}
