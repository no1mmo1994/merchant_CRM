import { Suspense } from "react";

import { PageHeader } from "@/components/layout/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { MenuClient } from "./menu-client";

export default function MenuPage() {
  return (
    <div className="space-y-6 p-6">
      <PageHeader
        title="Thực đơn"
        description="Món, danh mục và nhóm tùy chọn thêm — quản lý và liên kết ở cùng một nơi."
      />
      {/* MenuClient reads the active tab from the URL via useSearchParams,
          which Next requires inside a Suspense boundary. */}
      <Suspense fallback={<Skeleton className="h-96 w-full rounded-xl" />}>
        <MenuClient />
      </Suspense>
    </div>
  );
}
