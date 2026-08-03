"use client";

import * as React from "react";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { ChevronDown, ChevronRight, GripVertical, ImageIcon, ListChecks, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import {
  useCreateItem,
  useDeleteCategory,
  useUpdateItemAvailability,
  useUploadItemImage,
} from "@/lib/api/menu";
import { ApiError } from "@/lib/api";
import { EditItemDialog } from "@/components/menu/EditItemDialog";
import { ItemAvailabilityDialog } from "@/components/menu/ItemAvailabilityDialog";
import { toast } from "sonner";

/** A modifier group attached to a menu item (e.g. "Topping"). */
export interface ItemModifierGroup {
  modifier_group_id: string;
  modifier_group_name: string;
  selection_range_min: number;
  selection_range_max: number;
  modifiers: Array<{
    modifier_id: string;
    modifier_name: string;
    price_vnd: number;
    price_display?: string | null;
  }>;
}

export interface MenuItemData {
  id: string;
  name: string;
  price?: number;
  description?: string;
  imageUrl?: string;
  available?: boolean;
  /**
   * Ẩn hoàn toàn khỏi menu khách (eligibleSellingStatus=INELIGIBLE).
   * Khác với `available=false` — item vẫn hiển thị ở storefront, chỉ
   * không order được. `hidden=true` thì item biến mất cho tới khi bật lại.
   */
  hidden?: boolean;
  /** Modifier groups attached to this item (parsed from Grab's `modifierGroups`). */
  modifierGroups?: ItemModifierGroup[];
}

export interface CategoryData {
  id: string;
  name: string;
  itemCount?: number;
  items?: MenuItemData[];
}

interface CategoryCardProps {
  category: CategoryData;
  onDelete?: (id: string) => void;
}

/** Format price as Vietnamese Dong */
function formatVND(price: number): string {
  return new Intl.NumberFormat("vi-VN", {
    style: "currency",
    currency: "VND",
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(price);
}

/**
 * Sortable category card. Wraps the DnD kit's `useSortable` hook so the
 * parent <SortableContext> in MenuTree can reorder us. The card also hosts
 * a "quick add item" form so power-users can create menu items inline.
 * When the category has items, they are rendered in an expandable section.
 */
export function CategoryCard({ category, onDelete }: CategoryCardProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: category.id });

  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.6 : 1,
  };

  const [expanded, setExpanded] = React.useState(true);
  const [adding, setAdding] = React.useState(false);
  const [name, setName] = React.useState("");
  const [price, setPrice] = React.useState("");

  const hasItems = Boolean(category.items && category.items.length > 0);

  const createItem = useCreateItem();
  const uploadImage = useUploadItemImage();
  const deleteCategory = useDeleteCategory();

  async function handleAddItem(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) {
      toast.error("Tên món là bắt buộc");
      return;
    }
    const priceVnd = Number(price.replace(/[^0-9]/g, ""));
    if (!priceVnd || priceVnd <= 0) {
      toast.error("Nhập giá hợp lệ bằng VND");
      return;
    }
    try {
      await createItem.mutateAsync({
        name: name.trim(),
        price_vnd: priceVnd,
        category_id: category.id,
      });
      toast.success(`Đã tạo "${name.trim()}"`);
      setName("");
      setPrice("");
      setAdding(false);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Tạo món thất bại");
    }
  }

  async function handleDelete() {
    if (!confirm(`Xóa danh mục "${category.name}"? Thao tác này không thể hoàn tác.`)) return;
    try {
      await deleteCategory.mutateAsync(category.id);
      toast.success(`Đã xóa "${category.name}"`);
      onDelete?.(category.id);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Xóa danh mục thất bại");
    }
  }

  // expose upload hook so parents can wire an image-drop handler if needed
  void uploadImage;

  return (
    <div
      ref={setNodeRef}
      style={style}
      className="group rounded-lg border border-(--color-border) bg-(--color-surface) shadow-sm"
    >
      {/* Category header */}
      <div className="flex items-center gap-2 p-3">
        <button
          type="button"
          {...attributes}
          {...listeners}
          aria-label="Drag to reorder"
          className="cursor-grab touch-none rounded p-1 text-(--color-muted-foreground) hover:bg-(--color-surface-2) active:cursor-grabbing"
        >
          <GripVertical className="h-4 w-4" />
        </button>

        {/* Expand/collapse button — only when items exist */}
        {hasItems && (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="flex h-6 w-6 items-center justify-center rounded text-(--color-muted-foreground) hover:bg-(--color-surface-2)"
            aria-label={expanded ? "Thu gọn" : "Mở rộng"}
          >
            {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          </button>
        )}

        <div className="flex-1 min-w-0">
          <div className="truncate text-sm font-medium text-(--color-foreground)">
            {category.name}
          </div>
          {typeof category.itemCount === "number" && (
            <div className="text-xs text-(--color-muted-foreground)">
              {category.itemCount} món
            </div>
          )}
          {/* Grab categoryID — useful for debugging / cross-reference with
              the merchant script. Kept muted + monospace + truncated so it
              doesn't crowd the header. */}
          <div
            className="truncate font-mono text-[10px] text-(--color-muted-foreground)/70"
            title={category.id}
          >
            {category.id}
          </div>
        </div>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7"
          onClick={() => setAdding((v) => !v)}
          aria-label="Add item"
        >
          <Plus className="h-3.5 w-3.5" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 text-red-500 hover:bg-red-500/10 hover:text-red-500"
          onClick={handleDelete}
          aria-label="Delete category"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      </div>

      {/* Quick add form */}
      {adding && (
        <form onSubmit={handleAddItem} className="mx-3 mb-3 space-y-2 border-t border-(--color-border) pt-3">
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Tên món (tiếng Việt)"
            className="h-8 text-sm"
            autoFocus
          />
          <Input
            value={price}
            onChange={(e) => setPrice(e.target.value)}
            placeholder="Giá (VND)"
            inputMode="numeric"
            className="h-8 text-sm"
          />
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" size="sm" onClick={() => setAdding(false)}>
              Hủy
            </Button>
            <Button
              type="submit"
              size="sm"
              disabled={createItem.isPending}
              className="bg-(--color-brand) hover:bg-(--color-brand-hover) text-white"
            >
              {createItem.isPending ? "Đang thêm…" : "Thêm"}
            </Button>
          </div>
        </form>
      )}

      {/* Items list */}
      {expanded && hasItems && (
        <div className="border-t border-(--color-border)">
          {category.items!.map((item) => (
            <ItemRow key={item.id} item={item} categoryId={category.id} />
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * Single menu-item row: thumbnail + name + price + availability Switch +
 * edit button (opens a dialog). Description is rendered below the row
 * (no truncation) so it acts like a sub-label, matching the merchant
 * dashboard layout.
 */
interface ItemRowProps {
  item: MenuItemData;
  categoryId: string;
}

function ItemRow({ item, categoryId }: ItemRowProps) {
  const updateAvailability = useUpdateItemAvailability();
  const [stopDialogOpen, setStopDialogOpen] = React.useState(false);

  // Single source of truth for the Switch: derive from the cached query
  // (which itself has been optimistically mutated by `useUpdateItemAvailability`).
  // This avoids the dual-layer state where local + cache could disagree on
  // rollback. The cache's `onError` rolls back; on success the server
  // snapshot takes over.
  //
  // Available = sellable AND listed on the storefront. An item can be:
  //   - available=true,  hidden=false → bán được, hiển thị
  //   - available=false, hidden=false → không bán được, vẫn hiển thị
  //   - available=true,  hidden=true  → không hiển thị (trạng thái tạm thời
  //                                     khi merchant vừa ẩn nhưng chưa tắt)
  //   - available=false, hidden=true  → ẩn hoàn toàn
  // The Switch only reflects the "actually sellable & visible" composite.
  const available = !item.hidden && (item.available ?? true);

  async function handleToggle(next: boolean) {
    // OFF (next=false) → open dialog so the merchant picks a reason
    // (matches screenshot "Đổi trạng thái" UX).
    if (!next) {
      setStopDialogOpen(true);
      return;
    }
    // ON (next=true) → restore both sold-out + visibility. The backend
    // grabs the current sellingTimeID from the menu snapshot so we don't
    // need to fetch it here.
    try {
      await updateAvailability.mutateAsync({
        itemId: item.id,
        input: { status: 1, hidden: false },
      });
      toast.success(`Đã bật "${item.name}"`);
    } catch (err) {
      const msg = err instanceof ApiError
        ? err.message
        : err instanceof Error
        ? err.message
        : "Đổi trạng thái món thất bại";
      toast.error(msg);
    }
  }

  return (
    <div className="border-b border-(--color-border) px-3 py-2.5 last:border-b-0 hover:bg-(--color-surface-2)">
      <div className="flex items-center gap-3">
        {/* Item image */}
        <div className="h-12 w-12 flex-shrink-0 overflow-hidden rounded-md bg-(--color-surface-2)">
          {item.imageUrl ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={item.imageUrl}
              alt={item.name}
              className="h-full w-full object-cover"
              onError={(e) => {
                (e.target as HTMLImageElement).style.display = "none";
                (e.target as HTMLImageElement).nextElementSibling?.classList.remove("hidden");
              }}
            />
          ) : null}
          <div className={`flex h-full w-full items-center justify-center ${item.imageUrl ? "hidden" : ""}`}>
            <ImageIcon className="h-5 w-5 text-(--color-muted-foreground)" />
          </div>
        </div>

        {/* Item info — name + price (price still on the right column for alignment) */}
        <div className="min-w-0 flex-1">
          <div
            className={`truncate text-sm font-medium ${
              available ? "text-(--color-foreground)" : "text-(--color-muted-foreground)"
            }`}
          >
            {item.name}
          </div>
        </div>

        {/* Price */}
        <div className="flex-shrink-0 text-right">
          {item.price !== undefined ? (
            <span className="text-sm font-semibold text-(--color-brand)">
              {formatVND(item.price)}
            </span>
          ) : (
            <span className="text-xs text-(--color-muted-foreground)">Chưa đặt giá</span>
          )}
        </div>

        {/* Availability Switch */}
        <div className="flex-shrink-0">
          <Switch
            checked={available}
            onCheckedChange={handleToggle}
            aria-label={`Bật/tắt ${item.name}`}
          />
        </div>

        {/* Edit button */}
        <EditItemDialog item={item} categoryId={categoryId} />
      </div>

      {/* Description shown verbatim below the row (no truncation) */}
      {item.description && item.description.trim() && (
        <p
          className={`mt-1.5 break-words text-xs leading-relaxed ${
            available ? "text-(--color-muted-foreground)" : "text-(--color-muted-foreground)/60"
          }`}
        >
          {item.description}
        </p>
      )}

      {/* Grab itemID — displayed muted + monospace so the merchant can copy
          paste it into the edit script when needed. Indented to align with
          the row's body (past the 48px thumbnail). */}
      {item.id && (
        <p
          className="mt-0.5 truncate pl-[3.75rem] font-mono text-[10px] text-(--color-muted-foreground)/60"
          title={item.id}
        >
          {item.id}
        </p>
      )}

      {/* Modifier groups attached to this item */}
      {item.modifierGroups && item.modifierGroups.length > 0 && (
        <div className="mt-2 ml-[3.75rem] space-y-1.5">
          {item.modifierGroups.map((mg) => {
            const range =
              mg.selection_range_min === mg.selection_range_max
                ? `Chọn ${mg.selection_range_max}`
                : `Chọn ${mg.selection_range_min}–${mg.selection_range_max}`;
            return (
              <div
                key={mg.modifier_group_id || mg.modifier_group_name}
                className="flex items-start gap-2 rounded-md bg-(--color-surface-2)/50 px-2 py-1.5 text-xs"
              >
                <ListChecks className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-(--color-brand)" />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="font-medium text-(--color-foreground)">
                      {mg.modifier_group_name}
                    </span>
                    <Badge variant="outline" className="px-1.5 py-0 text-[10px]">
                      {range}
                    </Badge>
                    <Badge variant="secondary" className="px-1.5 py-0 text-[10px]">
                      {mg.modifiers.length} món
                    </Badge>
                  </div>
                  {mg.modifiers.length > 0 && (
                    <div className="mt-1 flex flex-wrap gap-1">
                      {mg.modifiers.slice(0, 5).map((m) => (
                        <span
                          key={m.modifier_id || m.modifier_name}
                          className="inline-flex items-center gap-1 rounded bg-(--color-surface) px-1.5 py-0.5 text-[10px] text-(--color-muted-foreground)"
                        >
                          {m.modifier_name}
                          {m.price_vnd > 0 ? (
                            <span className="text-(--color-brand)">
                              +{m.price_vnd.toLocaleString("vi-VN")}đ
                            </span>
                          ) : null}
                        </span>
                      ))}
                      {mg.modifiers.length > 5 && (
                        <span className="text-[10px] text-(--color-muted-foreground)">
                          +{mg.modifiers.length - 5} khác
                        </span>
                      )}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Status-change dialog (mirrors Grab's mobile "Đổi trạng thái" UX).
          Controlled by the Switch's OFF path so the merchant picks a
          reason (today / forever / hide). ON path bypasses the dialog. */}
      <ItemAvailabilityDialog
        item={item}
        open={stopDialogOpen}
        onOpenChange={setStopDialogOpen}
      />
    </div>
  );
}
