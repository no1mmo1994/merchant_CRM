"use client";

import * as React from "react";
import { useMenu } from "@/lib/api/menu";
import { MenuTree } from "@/components/menu/MenuTree";
import { NewItemDialog } from "@/components/menu/NewItemDialog";
import { ApiError } from "@/lib/api";
import { toast } from "sonner";

function parseCategories(menu?: Record<string, unknown>): { id: string; name: string }[] {
  if (!menu) return [];
  const raw =
    (Array.isArray(menu) ? menu : null) ??
    (Array.isArray((menu as { categories?: unknown }).categories)
      ? (menu as { categories: unknown[] }).categories
      : null) ??
    (Array.isArray((menu as { data?: unknown }).data)
      ? (menu as { data: unknown[] }).data
      : null) ??
    [];

  return (raw as unknown[]).map((c, idx) => {
    const obj = (c ?? {}) as Record<string, unknown>;
    return {
      id: String(obj.categoryID ?? obj.id ?? obj.resourceID ?? `cat-${idx}`),
      name: String(obj.name ?? obj.title ?? obj.categoryName ?? "Untitled"),
    };
  });
}

export function MenuClient() {
  const { data, isLoading, error } = useMenu();

  React.useEffect(() => {
    if (error instanceof ApiError) {
      toast.error(`Không thể tải thực đơn: ${error.message}`);
    }
  }, [error]);

  const categories = React.useMemo(() => parseCategories(data), [data]);

  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <div className="lg:col-span-2">
        <MenuTree menu={data} isLoading={isLoading} />
      </div>
      <div className="space-y-4">
        <div className="rounded-lg border border-(--color-border) bg-(--color-surface) p-4">
          <div className="text-sm font-medium text-(--color-foreground)">Thao tác nhanh</div>
          <div className="mt-1 text-xs text-(--color-muted-foreground)">
            Tạo món mới hoặc sắp xếp lại danh mục.
          </div>
          <div className="mt-3">
            <NewItemDialog categories={categories} />
          </div>
        </div>
        <div className="rounded-lg border border-(--color-border) bg-(--color-surface) p-4 text-sm">
          <div className="font-medium text-(--color-foreground)">Mẹo</div>
          <ul className="mt-2 space-y-1.5 text-(--color-muted-foreground)">
            <li>• Kéo danh mục bằng núm để sắp xếp lại.</li>
            <li>• Nhấn + trên thẻ danh mục để nhanh chóng thêm món.</li>
            <li>• Tên tiếng Việt được tự động dịch khi lưu.</li>
          </ul>
        </div>
      </div>
    </div>
  );
}
