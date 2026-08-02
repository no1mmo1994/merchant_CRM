import { PageHeader } from "@/components/layout/page-header";
import { SettingsClient } from "./settings-client";

export default function SettingsPage() {
  return (
    <div className="space-y-6 p-6">
      <PageHeader
        title="Cài đặt"
        description="Token, phiên đăng nhập, lịch đồng bộ và nhật ký hoạt động."
      />
      <SettingsClient />
    </div>
  );
}
