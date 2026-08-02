"use client";

import * as React from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Plus } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { useCreateItem } from "@/lib/api/menu";
import { ItemImageUploader } from "./ItemImageUploader";

const itemSchema = z.object({
  name: z.string().min(1, "Tên là bắt buộc").max(120),
  description: z.string().max(500).optional(),
  price: z
    .string()
    .min(1, "Giá là bắt buộc")
    .refine((v) => /^\d+$/.test(v.replace(/[^0-9]/g, "")), "Giá phải là số nguyên dương"),
  categoryId: z.string().min(1, "Chọn danh mục"),
});

type ItemFormValues = z.infer<typeof itemSchema>;

interface NewItemDialogProps {
  /** Available categories (id, name) for the select. */
  categories: { id: string; name: string }[];
  defaultCategoryId?: string;
  /** Render-prop trigger so callers can place a custom button. */
  children?: React.ReactNode;
}

/**
 * "Create item" dialog. Uses react-hook-form + zod for validation and
 * the ItemImageUploader for image handling. Disabled when there are no
 * categories so users can't create orphaned items.
 */
export function NewItemDialog({ categories, defaultCategoryId, children }: NewItemDialogProps) {
  const [open, setOpen] = React.useState(false);
  const [images, setImages] = React.useState<string[]>([]);
  const createItem = useCreateItem();

  const form = useForm<ItemFormValues>({
    resolver: zodResolver(itemSchema),
    defaultValues: {
      name: "",
      description: "",
      price: "",
      categoryId: defaultCategoryId ?? categories[0]?.id ?? "",
    },
  });

  // Keep categoryId in sync when defaultCategoryId changes
  React.useEffect(() => {
    if (defaultCategoryId) form.setValue("categoryId", defaultCategoryId);
  }, [defaultCategoryId, form]);

  async function onSubmit(values: ItemFormValues) {
    try {
      await createItem.mutateAsync({
        name: values.name.trim(),
        description: values.description?.trim() || "",
        price_vnd: Number(values.price.replace(/[^0-9]/g, "")),
        category_id: values.categoryId,
        image_urls: images,
      });
      toast.success(`Đã tạo "${values.name}"`);
      form.reset();
      setImages([]);
      setOpen(false);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Tạo món thất bại");
    }
  }

  const noCategories = categories.length === 0;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={(props) =>
          children ? (
            <button type="button" {...props}>
              {children}
            </button>
          ) : (
            <Button
              {...props}
              className="bg-(--color-brand) text-white hover:bg-(--color-brand-hover)"
              disabled={noCategories}
            >
              <Plus className="mr-1.5 h-4 w-4" />
              Món mới
            </Button>
          )
        }
      />
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Thêm món mới</DialogTitle>
          <DialogDescription>
            Thêm một món mới vào danh mục. Tên tiếng Việt sẽ được Grab tự động dịch khi lưu.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="item-name">Tên (tiếng Việt)</Label>
            <Input id="item-name" {...form.register("name")} placeholder="Phở bò tái" />
            {form.formState.errors.name && (
              <p className="text-xs text-red-500">{form.formState.errors.name.message}</p>
            )}
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="item-desc">Mô tả (tùy chọn)</Label>
            <Input
              id="item-desc"
              {...form.register("description")}
              placeholder="Mì xào bò"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="item-price">Giá (VND)</Label>
              <Input
                id="item-price"
                inputMode="numeric"
                placeholder="65000"
                {...form.register("price")}
              />
              {form.formState.errors.price && (
                <p className="text-xs text-red-500">{form.formState.errors.price.message}</p>
              )}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="item-category">Danh mục</Label>
              <select
                id="item-category"
                className="h-9 w-full rounded-md border border-(--color-border) bg-(--color-surface) px-2 text-sm"
                {...form.register("categoryId")}
              >
                {categories.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
              {form.formState.errors.categoryId && (
                <p className="text-xs text-red-500">{form.formState.errors.categoryId.message}</p>
              )}
            </div>
          </div>

          <div className="space-y-1.5">
            <Label>Hình ảnh</Label>
            <ItemImageUploader value={images} onChange={setImages} max={4} />
          </div>

          <DialogFooter className="gap-2">
            <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
              Hủy
            </Button>
            <Button
              type="submit"
              disabled={createItem.isPending || noCategories}
              className="bg-(--color-brand) text-white hover:bg-(--color-brand-hover)"
            >
              {createItem.isPending ? "Đang tạo…" : "Tạo món"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
