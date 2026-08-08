import { PageHeader } from "@/components/layout/page-header";
import { MarketingClient } from "./marketing-client";

/**
 * /marketing — Tiếp thị page.
 *
 * Server shell + client data binding, same split as /finance and
 * /modifiers.
 */
export default function MarketingPage() {
  return (
    <div className="space-y-6 p-6">
      <PageHeader
        title="Tiếp thị"
        description="Chương trình Grab đang mời và các chiến dịch cửa hàng đang chạy, kèm hiệu suất."
      />
      <MarketingClient />
    </div>
  );
}
