"use client";

import * as React from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ApiError } from "@/lib/api";
import { useUpdateItemAvailability } from "@/lib/api/menu";
import type { MenuItemData } from "@/components/menu/CategoryCard";

interface ItemAvailabilityDialogProps {
  item: MenuItemData;
  /** Optional explicit open state — if absent the dialog manages itself. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** Triggered after a successful status change (1|2|3). */
  onApplied?: (status: 1 | 2 | 3) => void;
}

/**
 * Each row in the "Đổi trạng thái" dialog is a separate action, NOT a
 * radio choice. Tapping a row commits the matching backend call.
 *
 * Semantics (verified against Grab's v1 endpoint enum, mirror of
 * Menu/monan/bat_tatmon.py and hide_monan.py):
 *   - "Hết bán hôm nay"     → status=2  (item still listed, cannot be
 *                                     ordered until midnight, auto-reset)
 *   - "Không về hàng nữa"   → status=3  (item still listed, cannot be
 *                                     ordered until merchant toggles back)
 *   - "Ẩn mục này"          → status=7  (item hidden from storefront
 *                                     entirely; merchant dashboard still
 *                                     shows it with "ẩn giấu" badge)
 *   - "Bật lại / Hiển thị"  → status=1  (restore sellable + visible)
 */
type ActionKind = "status_2" | "status_3" | "hide" | "restore";

interface DialogAction {
  kind: ActionKind;
  /** Short Vietnamese button label. */
  label: string;
  /** Body description shown under the label. */
  description: string;
  /** Tailwind classes for the action button. */
  buttonClass: string;
}

const ACTIONS: DialogAction[] = [
  {
    kind: "status_2",
    label: "Hết bán hôm nay",
    description: "Món vẫn hiển thị nhưng không thể order, tự bật lại vào 0h hôm sau.",
    buttonClass:
      "w-full bg-amber-500 text-white hover:bg-amber-600",
  },
  {
    kind: "status_3",
    label: "Không về hàng nữa",
    description:
      "Món vẫn hiển thị với khách nhưng không thể order cho tới khi bật lại.",
    buttonClass:
      "w-full bg-orange-500 text-white hover:bg-orange-600",
  },
  {
    kind: "hide",
    label: "Ẩn mục này",
    description:
      "Món sẽ bị ẩn khỏi menu cho khách cho tới khi bật lại. Merchant vẫn chỉnh sửa được.",
    buttonClass: "w-full bg-red-500 text-white hover:bg-red-600",
  },
];

export function ItemAvailabilityDialog({
  item,
  open: controlledOpen,
  onOpenChange: controlledOnOpenChange,
  onApplied,
}: ItemAvailabilityDialogProps) {
  const [internalOpen, setInternalOpen] = React.useState(false);
  const isControlled = controlledOpen !== undefined;
  const open = isControlled ? controlledOpen : internalOpen;
  const setOpen = (v: boolean) => {
    if (!isControlled) setInternalOpen(v);
    controlledOnOpenChange?.(v);
  };

  const updateAvailability = useUpdateItemAvailability();
  // Default to "Hết bán hôm nay" since that's the most common OFF reason.
  const [pending, setPending] = React.useState<ActionKind | null>(null);

  // Reset pending state when dialog closes so reopening starts fresh.
  React.useEffect(() => {
    if (!open) setPending(null);
  }, [open]);

  const isHidden = Boolean(item.hidden);
  const isSoldOut = !(item.available ?? true);

  async function applyAction(kind: ActionKind) {
    setPending(kind);
    try {
      if (kind === "restore") {
        await updateAvailability.mutateAsync({
          itemId: item.id,
          input: { status: 1 },
        });
        toast.success(`Đã bật lại "${item.name}"`);
        onApplied?.(1);
      } else if (kind === "status_2") {
        await updateAvailability.mutateAsync({
          itemId: item.id,
          input: { status: 2 },
        });
        toast.success(`Đã tạm hết "${item.name}"`);
        onApplied?.(2);
      } else if (kind === "status_3") {
        await updateAvailability.mutateAsync({
          itemId: item.id,
          input: { status: 3 },
        });
        toast.success(`Đã ngưng bán "${item.name}"`);
        onApplied?.(3);
      } else if (kind === "hide") {
        await updateAvailability.mutateAsync({
          itemId: item.id,
          input: { status: 7 },
        });
        toast.success(`Đã ẩn "${item.name}" khỏi menu khách`);
      }
      setOpen(false);
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
          ? err.message
          : "Đổi trạng thái món thất bại";
      toast.error(msg);
    } finally {
      setPending(null);
    }
  }

  const busy = updateAvailability.isPending || pending !== null;

  // We have three possible UX paths depending on the item's current state:
  //   A. Item is fully on (available && !hidden) → show 3 OFF actions.
  //   B. Item is sold-out (status=2|3) but visible → show "Bật lại" + the
  //      other OFF actions so the merchant can also "Ẩn mục này" later.
  //   C. Item is hidden (eligibleSellingStatus=INELIGIBLE) → show "Hiển thị
  //      lại" (restore) prominently, plus the OFF actions still work because
  //      the backend applies them sequentially (visibility + status).
  const renderActions = (): DialogAction[] => {
    if (isHidden) return ACTIONS; // hide is still applicable (idempotent)
    if (isSoldOut) return ACTIONS; // allow hiding a sold-out item too
    return ACTIONS;
  };

  const showRestore = isSoldOut || isHidden;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="max-h-[90vh] w-[calc(100vw-2rem)] overflow-y-auto sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Đổi trạng thái</DialogTitle>
          <DialogDescription>
            <span className="font-medium text-(--color-foreground)">{item.name}</span>
            {isHidden
              ? " đang bị ẩn khỏi menu khách. Bật lại để hiển thị trên storefront."
              : isSoldOut
              ? " đang tạm ngưng bán. Bật lại để cho khách order."
              : " — chọn lý do tắt món."}
          </DialogDescription>
        </DialogHeader>

        {/* Restore card (shown when item is currently off) */}
        {showRestore && (
          <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3">
            <div className="mb-2 text-xs font-medium uppercase tracking-wide text-emerald-700">
              Bật lại
            </div>
            <Button
              type="button"
              onClick={() => applyAction("restore")}
              disabled={busy}
              className="w-full bg-emerald-600 text-white hover:bg-emerald-700"
            >
              {pending === "restore"
                ? "Đang bật lại…"
                : isHidden
                ? "Hiển thị món này lại"
                : "Bật bán trở lại"}
            </Button>
            <p className="mt-1.5 text-xs text-emerald-700/80">
              Khôi phục cả trạng thái bán lẫn hiển thị trên menu khách.
            </p>
          </div>
        )}

        {/* Stop / hide actions */}
        <div className="space-y-2">
          {!showRestore && (
            <div className="text-xs font-medium uppercase tracking-wide text-(--color-muted-foreground)">
              Tắt món
            </div>
          )}
          {renderActions().map((action) => {
            const disabled = busy;
            const isCurrent = pending === action.kind;
            return (
              <div
                key={action.kind}
                className="rounded-lg border border-(--color-border) p-3"
              >
                <Button
                  type="button"
                  onClick={() => applyAction(action.kind)}
                  disabled={disabled}
                  className={action.buttonClass}
                >
                  {isCurrent ? "Đang lưu…" : action.label}
                </Button>
                <p className="mt-1.5 text-xs leading-relaxed text-(--color-muted-foreground)">
                  {action.description}
                </p>
              </div>
            );
          })}
        </div>

        <DialogFooter className="-mx-4 -mb-4 mt-2">
          <Button
            type="button"
            variant="ghost"
            onClick={() => setOpen(false)}
            disabled={busy}
            className="w-full"
          >
            Đóng
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}