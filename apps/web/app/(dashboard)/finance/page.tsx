import { PageHeader } from "@/components/layout/page-header";
import { FinanceClient } from "./finance-client";

/**
 * /finance — Tài chính page.
 *
 * The page shell is intentionally a server component so the
 * sidebar layout + auth guard stay declarative. The data binding
 * (date picker + KPI cards + drill-down list) lives in
 * `finance-client.tsx`, matching the modifiers / stores / settings
 * pattern elsewhere on the dashboard.
 */
export default function FinancePage() {
  return (
    <div className="space-y-6 p-6">
      <PageHeader
        title="Tài chính"
        description="Báo cáo doanh thu, số dư và các khoản khấu trừ đồng bộ trực tiếp từ Grab Merchant."
      />
      <FinanceClient />
    </div>
  );
}
