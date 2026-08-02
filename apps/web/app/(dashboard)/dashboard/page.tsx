import { PageHeader } from "@/components/layout/page-header";
import { DashboardGrid } from "@/components/dashboard/DashboardGrid";

export default function DashboardPage() {
  return (
    <div className="space-y-6 p-6">
      <PageHeader
        title="Tổng quan"
        description="Tổng quan tình trạng thực đơn trên tất cả cửa hàng Grab."
      />
      <DashboardGrid />
    </div>
  );
}
