"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ListChecks, ShoppingBag } from "lucide-react";

import { useMenu } from "@/lib/api/menu";
import { MenuTree } from "@/components/menu/MenuTree";
import { NewItemDialog } from "@/components/menu/NewItemDialog";
import { ModifiersClient } from "@/app/(dashboard)/modifiers/modifiers-client";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ApiError } from "@/lib/api";
import { toast } from "sonner";

/**
 * The two menu-management surfaces live under one page as tabs: the
 * dishes/categories tree, and the modifier (add-on) groups plus their
 * item links. They were two separate sidebar entries, which split one job
 * — building the menu — across two places; a group only matters in
 * relation to the items it attaches to, so managing both here keeps that
 * relationship in view.
 */

type MenuTab = "items" | "addons";

const TABS: ReadonlyArray<{ value: MenuTab; label: string; icon: typeof ShoppingBag }> = [
  { value: "items", label: "Món & danh mục", icon: ShoppingBag },
  { value: "addons", label: "Tùy chọn thêm", icon: ListChecks },
];

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

/** Dishes + categories tree with the quick-action rail. */
function ItemsTab() {
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
            <li>• Gán nhóm tùy chọn cho món ở tab &quot;Tùy chọn thêm&quot;.</li>
          </ul>
        </div>
      </div>
    </div>
  );
}

export function MenuClient() {
  const router = useRouter();
  const searchParams = useSearchParams();
  // The tab lives in the URL so the old /modifiers route can redirect
  // straight to the add-ons tab, and so a shared link reopens the same
  // view. Anything other than a known tab falls back to items.
  const paramTab = searchParams.get("tab");
  const activeTab: MenuTab = paramTab === "addons" ? "addons" : "items";

  const setTab = React.useCallback(
    (next: string) => {
      const params = new URLSearchParams(searchParams.toString());
      if (next === "items") params.delete("tab");
      else params.set("tab", next);
      const query = params.toString();
      // `replace`, not `push`: flipping tabs shouldn't stack Back-button
      // history the way navigating to a different page would.
      router.replace(query ? `/menu?${query}` : "/menu", { scroll: false });
    },
    [router, searchParams],
  );

  return (
    <Tabs value={activeTab} onValueChange={setTab}>
      <TabsList>
        {TABS.map(({ value, label, icon: Icon }) => (
          <TabsTrigger key={value} value={value}>
            <Icon className="h-4 w-4" />
            {label}
          </TabsTrigger>
        ))}
      </TabsList>

      <TabsContent value="items" className="mt-4">
        <ItemsTab />
      </TabsContent>
      {/* keepMounted: base-ui unmounts an inactive panel by default, which
          would throw away an open "liên kết món" dialog and its unsaved
          selection if the URL's tab flips via browser Back/Forward. Kept
          mounted, the add-ons subtree — and any open dialog — survives a
          tab switch; the cost is one modifier-list fetch on page load. */}
      <TabsContent value="addons" keepMounted className="mt-4">
        <ModifiersClient />
      </TabsContent>
    </Tabs>
  );
}
