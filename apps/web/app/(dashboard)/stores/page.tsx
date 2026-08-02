import { PageHeader } from "@/components/layout/page-header";
import { StoresClient } from "./stores-client";

export default function StoresPage() {
  return (
    <div className="space-y-6 p-6">
      <PageHeader
        title="Cửa hàng"
        description="Kết nối, chuyển đổi và kiểm tra cửa hàng Grab Merchant."
      />
      <StoresClient />
    </div>
  );
}
