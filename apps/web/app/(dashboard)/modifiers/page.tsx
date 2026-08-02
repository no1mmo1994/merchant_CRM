import { PageHeader } from "@/components/layout/page-header";
import { ModifiersClient } from "./modifiers-client";

export default function ModifiersPage() {
  return (
    <div className="space-y-6 p-6">
      <PageHeader
        title="Nhóm tùy chọn"
        description="Phần thêm, kích thước và lựa chọn bắt buộc."
      />
      <ModifiersClient />
    </div>
  );
}
