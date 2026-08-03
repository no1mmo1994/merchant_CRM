"use client";

import * as React from "react";
import {
  DndContext,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { Plus, RefreshCw } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { CategoryCard, type CategoryData, type MenuItemData } from "./CategoryCard";
import { useCreateCategory, useSortCategories, MENU_KEY, type MenuPayload } from "@/lib/api/menu";
import { Skeleton } from "@/components/ui/skeleton";
import { toast } from "sonner";
import { useIsFetching, useQueryClient } from "@tanstack/react-query";

interface MenuTreeProps {
  /** Menu payload from /api/menu. We only need the categories list shape. */
  menu?: MenuPayload;
  isLoading?: boolean;
}

/**
 * Parse the categories out of the Grab menu dict.
 * Grab returns: { categories: [{ categoryID, categoryName, items: [{ itemID, itemName, priceInMin, description, imageURL }] }] }
 */
function parseCategories(menu?: MenuPayload): CategoryData[] {
  if (!menu) return [];

  // Grab returns { categories: [...] } or { data: [...] }
  const rawCats = (
    Array.isArray((menu as { categories?: unknown }).categories)
      ? (menu as { categories: unknown[] }).categories
      : null) ??
    (Array.isArray((menu as { data?: unknown }).data)
      ? (menu as { data: unknown[] }).data
      : null) ??
    (Array.isArray(menu) ? menu : null) ??
    [];

  return (rawCats as unknown[]).map((c, idx) => {
    const obj = (c ?? {}) as Record<string, unknown>;
    const id = String(obj.categoryID ?? obj.id ?? obj.resourceID ?? `cat-${idx}`);
    // Grab uses categoryName, not name
    const name = String(obj.categoryName ?? obj.name ?? obj.title ?? "Danh mục");
    const rawItems = Array.isArray(obj.items) ? (obj.items as unknown[]) : [];

    const items: MenuItemData[] = rawItems.map((rawItem, itemIdx) => {
      const item = (rawItem ?? {}) as Record<string, unknown>;
      const itemId = String(item.itemID ?? item.skuID ?? item.id ?? `item-${idx}-${itemIdx}`);
      // Grab uses itemName, not name
      const itemName = String(item.itemName ?? item.name ?? item.title ?? "Món không tên");
      // Grab uses priceInMin (in VND cents/minor units)
      const price = item.priceInMin ?? item.price;
      // Grab uses imageURL (singular)
      const imageUrl = String(item.imageURL ?? item.imageUrl ?? item.photo ?? "");
      const description = String(item.description ?? item.desc ?? "");
      // Grab v1 enum: 1=AVAILABLE, 2=OUT_OF_STOCK_TODAY, 3=OUT_OF_STOCK,
      // 7=HIDDEN (verified against Menu/monan/hide_monan.py).
      const availableStatus = Number(item.availableStatus ?? 1);
      // Status 7 means the item is hidden from the customer menu entirely.
      // Items 2/3 stay visible but unorderable. We surface `hidden` so the
      // Switch + dialog can react distinctly to "hidden" vs "sold-out".
      const hidden = availableStatus === 7;

      // Parse modifier groups embedded inside each item.
      // Grab shape: { modifierGroups: [{ modifierGroupID, modifierGroupName,
      //   selectionRangeMin, selectionRangeMax, modifiers: [...] }] }
      const rawModGroups = Array.isArray(item.modifierGroups)
        ? (item.modifierGroups as unknown[])
        : [];
      const modifierGroups: NonNullable<MenuItemData["modifierGroups"]> =
        rawModGroups
          .map((rawMg) => {
            const mg = (rawMg ?? {}) as Record<string, unknown>;
            const rawMods = Array.isArray(mg.modifiers)
              ? (mg.modifiers as unknown[])
              : [];
            const modifiers = rawMods
              .map((rawMod) => {
                const m = (rawMod ?? {}) as Record<string, unknown>;
                return {
                  modifier_id: String(
                    m.modifierID ?? m.id ?? ""
                  ),
                  modifier_name: String(
                    m.modifierName ?? m.name ?? ""
                  ),
                  price_vnd: Number(m.priceInMin ?? m.price ?? 0),
                  price_display:
                    typeof m.priceDisplay === "string"
                      ? m.priceDisplay
                      : null,
                };
              })
              .filter((m) => m.modifier_name);
            return {
              modifier_group_id: String(
                mg.modifierGroupID ?? mg.id ?? ""
              ),
              modifier_group_name: String(
                mg.modifierGroupName ?? mg.name ?? ""
              ),
              selection_range_min: Number(mg.selectionRangeMin ?? 0),
              selection_range_max: Number(mg.selectionRangeMax ?? 1),
              modifiers,
            };
          })
          .filter((mg) => mg.modifier_group_name);

      return {
        id: itemId,
        name: itemName,
        price: typeof price === "number" ? price : undefined,
        description: description || undefined,
        imageUrl: imageUrl || undefined,
        // available means "sellable" (status 1). Items 2/3 are sold-out but
        // still listed, so they show as OFF. Status 7 is hidden — Switch is
        // OFF too because it can't be ordered.
        available: availableStatus === 1,
        hidden,
        availableStatus,
        modifierGroups:
          modifierGroups.length > 0 ? modifierGroups : undefined,
      };
    });

    return {
      id,
      name,
      itemCount: items.length,
      items: items.length > 0 ? items : undefined,
    };
  });
}

export function MenuTree({ menu, isLoading }: MenuTreeProps) {
  const initial = React.useMemo(() => parseCategories(menu), [menu]);
  const [items, setItems] = React.useState<CategoryData[]>(initial);

  // Re-sync when server data changes (refetch / switch store).
  React.useEffect(() => {
    setItems(initial);
  }, [initial]);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } })
  );

  const createCategory = useCreateCategory();
  const sortCategories = useSortCategories();
  const qc = useQueryClient();
  // useIsFetching reports any in-flight query under MENU_KEY so the reload
  // button can spin while the refetch is running. This covers both the
  // initial load and any subsequent invalidation triggered elsewhere.
  const isReloading = useIsFetching({ queryKey: MENU_KEY }) > 0;

  function handleReload() {
    qc.invalidateQueries({ queryKey: MENU_KEY });
    toast.success("Đang tải lại thực đơn…");
  }
  const [newName, setNewName] = React.useState("");

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    const name = newName.trim();
    if (!name) return;
    try {
      await createCategory.mutateAsync({ name });
      setNewName("");
      toast.success(`Đã tạo "${name}"`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Tạo danh mục thất bại");
    }
  }

  async function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIndex = items.findIndex((i) => i.id === active.id);
    const newIndex = items.findIndex((i) => i.id === over.id);
    if (oldIndex < 0 || newIndex < 0) return;

    const next = arrayMove(items, oldIndex, newIndex);
    setItems(next);

    try {
      // Grab uses sortOrder = total - position (top item = highest sortOrder)
      const total = next.length;
      await sortCategories.mutateAsync({
        items: next.map((it, idx) => ({
          resource_id: it.id,
          sort_order: total - idx,
        })),
      });
    } catch (err) {
      // Roll back on failure.
      setItems(items);
      toast.error(err instanceof Error ? err.message : "Sắp xếp lại danh mục thất bại");
    }
  }

  return (
    <Card className="border-(--color-border)">
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle>Danh mục thực đơn</CardTitle>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={handleReload}
          disabled={isReloading}
          aria-label="Tải lại thực đơn"
          title="Tải lại thực đơn từ Grab"
          className="h-8 gap-1.5 text-(--color-muted-foreground) hover:text-(--color-foreground)"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${isReloading ? "animate-spin" : ""}`} />
          <span className="text-xs">Tải lại</span>
        </Button>
      </CardHeader>
      <CardContent className="space-y-4">
        <form onSubmit={handleAdd} className="flex gap-2">
          <Input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="Tên danh mục mới (tiếng Việt)"
            className="h-9"
          />
          <Button
            type="submit"
            disabled={createCategory.isPending}
            className="bg-(--color-brand) hover:bg-(--color-brand-hover) text-white"
          >
            <Plus className="mr-1.5 h-4 w-4" />
            {createCategory.isPending ? "Đang thêm…" : "Thêm"}
          </Button>
        </form>

        {isLoading ? (
          <div className="space-y-2">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-14 w-full" />
            ))}
          </div>
        ) : items.length === 0 ? (
          <div className="rounded-lg border border-dashed border-(--color-border) p-8 text-center text-sm text-(--color-muted-foreground)">
            Chưa có danh mục nào. Thêm một danh mục bên trên để bắt đầu.
          </div>
        ) : (
          <DndContext
            sensors={sensors}
            collisionDetection={closestCenter}
            onDragEnd={handleDragEnd}
          >
            <SortableContext items={items.map((i) => i.id)} strategy={verticalListSortingStrategy}>
              <div className="space-y-2">
                {items.map((cat) => (
                  <CategoryCard key={cat.id} category={cat} />
                ))}
              </div>
            </SortableContext>
          </DndContext>
        )}
      </CardContent>
    </Card>
  );
}
