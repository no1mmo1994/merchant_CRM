import { PageHeader } from "@/components/layout/page-header";
import { MenuClient } from "./menu-client";

export default function MenuPage() {
  return (
    <div className="space-y-6 p-6">
      <PageHeader
        title="Thực đơn"
        description="Danh mục và món ăn đã đồng bộ với Grab Merchant."
      />
      <MenuClient />
    </div>
  );
}
