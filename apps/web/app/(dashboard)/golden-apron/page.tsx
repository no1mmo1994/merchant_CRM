import { PageHeader } from "@/components/layout/page-header";

import { GoldenApronClient } from "./golden-apron-client";

export default function GoldenApronPage() {
  return (
    <div className="space-y-6 p-6">
      <PageHeader
        title="Tạp Dề Vàng"
        description="Hạng của cửa hàng và điều kiện cần đạt để lên hạng."
      />
      <GoldenApronClient />
    </div>
  );
}
