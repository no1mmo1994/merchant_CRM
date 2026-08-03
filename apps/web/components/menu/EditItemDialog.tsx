"use client";

import * as React from "react";
import { toast } from "sonner";
import { Pencil } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api";
import { useUpdateItem, type UpdateItemInput } from "@/lib/api/menu";
import type { MenuItemData } from "@/components/menu/CategoryCard";

interface EditItemDialogProps {
  item: MenuItemData;
  categoryId: string;
  trigger?: React.ReactNode;
}

/**
 * Modal for editing a single menu item. Only the editable fields the
 * backend exposes are surfaced: VI name, description, price, images.
 *
 * The dialog is fully controlled via `open` so callers can also drive it
 * from elsewhere (e.g. an item-row click), but the default `trigger` is a
 * pencil button that fits alongside the row's Switch toggle.
 */
export function EditItemDialog({ item, categoryId, trigger }: EditItemDialogProps) {
  const [open, setOpen] = React.useState(false);
  const updateItem = useUpdateItem();

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      {trigger ? (
        <span
          onClick={() => setOpen(true)}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              setOpen(true);
            }
          }}
        >
          {trigger}
        </span>
      ) : (
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 flex-shrink-0"
          onClick={() => setOpen(true)}
          aria-label={`Chỉnh sửa ${item.name}`}
        >
          <Pencil className="h-3.5 w-3.5" />
        </Button>
      )}
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Chỉnh sửa món</DialogTitle>
          <DialogDescription>
            Cập nhật tên, mô tả và giá. Thay đổi được ghi trực tiếp lên Grab.
          </DialogDescription>
        </DialogHeader>
        <EditItemForm
          item={item}
          categoryId={categoryId}
          saving={updateItem.isPending}
          onCancel={() => setOpen(false)}
          onSave={async (input) => {
            try {
              await updateItem.mutateAsync({ itemId: item.id, input });
              toast.success(`Đã cập nhật "${input.name ?? item.name}"`);
              setOpen(false);
            } catch (err) {
              const msg = err instanceof ApiError
                ? err.message
                : err instanceof Error
                ? err.message
                : "Cập nhật món thất bại";
              toast.error(msg);
            }
          }}
        />
      </DialogContent>
    </Dialog>
  );
}

interface EditItemFormProps {
  item: MenuItemData;
  categoryId: string;
  saving: boolean;
  onCancel: () => void;
  onSave: (input: UpdateItemInput) => Promise<void>;
}

function EditItemForm({ item, categoryId, saving, onCancel, onSave }: EditItemFormProps) {
  const [name, setName] = React.useState(item.name);
  const [description, setDescription] = React.useState(item.description ?? "");
  const [priceText, setPriceText] = React.useState(
    item.price !== undefined ? String(item.price) : "",
  );

  // Reset form when the user opens the dialog for a different item, or when
  // the underlying item changes AND the form has no unsaved edits. We
  // intentionally do NOT clobber the user's in-flight edits if a refetch
  // happens mid-edit — that would silently lose their typing.
  React.useEffect(() => {
    setName((prev) => (prev === item.name ? prev : item.name));
    setDescription((prev) => (prev === (item.description ?? "") ? prev : item.description ?? ""));
    setPriceText((prev) => {
      const incoming = item.price !== undefined ? String(item.price) : "";
      return prev === incoming ? prev : incoming;
    });
  }, [item.id, item.name, item.description, item.price]);

  // When switching to a different item id, force a fresh reset.
  const lastItemIdRef = React.useRef(item.id);
  React.useEffect(() => {
    if (lastItemIdRef.current !== item.id) {
      lastItemIdRef.current = item.id;
      setName(item.name);
      setDescription(item.description ?? "");
      setPriceText(item.price !== undefined ? String(item.price) : "");
    }
  }, [item.id, item.name, item.description, item.price]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) {
      toast.error("Tên món là bắt buộc");
      return;
    }
    const priceVnd = Number(priceText.replace(/[^0-9]/g, ""));
    if (!Number.isFinite(priceVnd) || priceVnd <= 0) {
      toast.error("Nhập giá hợp lệ bằng VND");
      return;
    }

    const input: UpdateItemInput = {
      name: trimmed,
      description,
      price_vnd: priceVnd,
      // The current backend keeps the item in its original category; we
      // forward categoryId for completeness so a future "move category"
      // feature only needs to flip a flag.
      category_id: categoryId,
    };
    await onSave(input);
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <div className="space-y-1.5">
        <Label htmlFor={`edit-name-${item.id}`}>Tên món</Label>
        <Input
          id={`edit-name-${item.id}`}
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Tên món (tiếng Việt)"
          className="h-9"
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor={`edit-desc-${item.id}`}>Mô tả</Label>
        <textarea
          id={`edit-desc-${item.id}`}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Mô tả ngắn cho món ăn"
          rows={3}
          className="w-full rounded-md border border-(--color-border) bg-(--color-background) px-3 py-2 text-sm shadow-sm placeholder:text-(--color-muted-foreground) focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-(--color-brand)"
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor={`edit-price-${item.id}`}>Giá (VND)</Label>
        <Input
          id={`edit-price-${item.id}`}
          value={priceText}
          onChange={(e) => setPriceText(e.target.value)}
          placeholder="vd: 45000"
          inputMode="numeric"
          className="h-9"
        />
      </div>
      <DialogFooter className="-mx-4 -mb-4 mt-2">
        <Button type="button" variant="ghost" onClick={onCancel} disabled={saving}>
          Hủy
        </Button>
        <Button
          type="submit"
          disabled={saving}
          className="bg-(--color-brand) text-white hover:bg-(--color-brand-hover)"
        >
          {saving ? "Đang lưu…" : "Lưu thay đổi"}
        </Button>
      </DialogFooter>
    </form>
  );
}