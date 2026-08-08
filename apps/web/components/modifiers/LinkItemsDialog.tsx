"use client";

import * as React from "react";
import { Check, Link2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api";
import { useMenu } from "@/lib/api/menu";
import { useSetGroupItems, type ModifierGroup } from "@/lib/api/modifiers";
import { cn } from "@/lib/utils";

type PickerItem = {
  id: string;
  name: string;
  priceVnd: number;
  imageUrl: string;
  categoryName: string;
  /** Whether this item already offers the group, per the live menu. */
  linked: boolean;
};

/**
 * Pull every menu item out of the `/api/menu` payload, along with whether
 * it already offers `groupId`.
 *
 * Walks BOTH wire shapes: the flat `categories` list and the nested
 * `sections[].categories` one. `MenuTree` only walks the flat list; on a
 * store that returns the nested shape that yields an empty picker, which
 * would read as "this store has no items" rather than "we didn't look
 * properly".
 */
function collectItems(menu: unknown, groupId: string): PickerItem[] {
  if (!menu || typeof menu !== "object") return [];
  const root = menu as Record<string, unknown>;

  const categories: Record<string, unknown>[] = [];
  const pushAll = (v: unknown) => {
    if (Array.isArray(v)) {
      for (const c of v) if (c && typeof c === "object") categories.push(c as Record<string, unknown>);
    }
  };
  // Four shapes, all of which `/api/menu` has been seen to return —
  // `MenuTree.parseCategories` already tolerates the first three.
  pushAll(root.categories);
  pushAll(root.data);
  if (Array.isArray(menu)) pushAll(menu);
  if (Array.isArray(root.sections)) {
    for (const s of root.sections) {
      if (s && typeof s === "object") pushAll((s as Record<string, unknown>).categories);
    }
  }

  const out: PickerItem[] = [];
  for (const cat of categories) {
    const categoryName = String(cat.categoryName ?? cat.name ?? "");
    const rawItems = Array.isArray(cat.items) ? cat.items : [];
    for (const raw of rawItems) {
      if (!raw || typeof raw !== "object") continue;
      const item = raw as Record<string, unknown>;
      const id = String(item.itemID ?? item.skuID ?? "");
      if (!id) continue;
      const images = Array.isArray(item.webPURLs)
        ? item.webPURLs
        : Array.isArray(item.imageURLs)
          ? item.imageURLs
          : [];
      // Must recognise link state EXACTLY as the backend's
      // `_item_references_group` does, including the legacy object shape.
      // If the two disagree the picker seeds wrong, and since saving sends
      // a desired end state, an item the picker thinks is unlinked gets
      // unlinked for real. A store on the object shape would have every
      // item shown as unticked and one Save would strip the group from
      // all of them.
      const linkedIds: string[] = [];
      const collectLinked = (v: unknown) => {
        if (!Array.isArray(v)) return;
        for (const entry of v) {
          if (typeof entry === "string") linkedIds.push(entry);
          else if (entry && typeof entry === "object") {
            const o = entry as Record<string, unknown>;
            const id = o.modifierGroupID ?? o.id;
            if (id) linkedIds.push(String(id));
          }
        }
      };
      collectLinked(item.linkedModifierGroupIDs);
      collectLinked(item.modifierGroups);
      out.push({
        id,
        name: String(item.itemName ?? item.name ?? "Món không tên"),
        priceVnd: Number(item.priceInMin ?? item.price ?? 0),
        imageUrl: String(item.webPURL ?? images[0] ?? ""),
        categoryName,
        linked: linkedIds.includes(groupId),
      });
    }
  }
  return out;
}

function formatVnd(value: number): string {
  return `${value.toLocaleString("vi-VN")}đ`;
}

export function LinkItemsDialog({
  group,
  onSaved,
}: {
  group: ModifierGroup;
  onSaved?: () => void;
}) {
  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState("");
  const [selected, setSelected] = React.useState<Set<string>>(new Set());
  const menu = useMenu();
  const setGroupItems = useSetGroupItems();

  // `useMenu()` already unwraps the envelope — `fetchMenu` returns
  // `res.menu`, so `menu.data` IS the Grab payload. Reading `.menu` off it
  // again yielded undefined and an empty picker, and TypeScript could not
  // catch it: `MenuPayload` is `Record<string, unknown>`, so `.menu` is a
  // legal `unknown` and `collectItems` accepts `unknown`.
  const items = React.useMemo(
    () => collectItems(menu.data, group.modifier_group_id),
    [menu.data, group.modifier_group_id],
  );

  // Seed the ticks from the live menu EXACTLY ONCE per open.
  //
  // The obvious version depends on `menu.data`, and that is a trap: this
  // component subscribes to the shared ["menu"] query for its whole
  // lifetime, so any refetch — a reconnect after the laptop wakes, or a
  // future same-page action that invalidates the menu — hands back a new
  // object, re-runs the effect, and silently replaces everything the
  // operator has ticked with whatever the server currently says.
  //
  // `seeded` also can't just be "did open flip", because the menu may
  // still be loading at that moment; we have to wait for data and then
  // seed, without seeding again afterwards.
  const seededRef = React.useRef(false);
  React.useEffect(() => {
    if (!open) {
      seededRef.current = false;
      return;
    }
    if (seededRef.current || menu.isLoading) return;
    seededRef.current = true;
    setQuery("");
    setSelected(new Set(items.filter((i) => i.linked).map((i) => i.id)));
  }, [open, menu.isLoading, items]);

  const visible = React.useMemo(() => {
    const q = query.trim().toLowerCase();
    const matched = !q
      ? items
      : items.filter(
          (i) =>
            i.name.toLowerCase().includes(q) || i.categoryName.toLowerCase().includes(q),
        );
    // Currently-linked items first. They are the ones an operator came
    // here to review or switch off; on a long menu they would otherwise be
    // scattered among dozens of unlinked ones and effectively unfindable.
    // Sorted on a copy — `items` is memoised and shared with the seeding
    // effect.
    return [...matched].sort((a, b) => {
      if (a.linked !== b.linked) return a.linked ? -1 : 1;
      return a.name.localeCompare(b.name, "vi");
    });
  }, [items, query]);

  // What pressing save would actually do, computed against the server's
  // current state rather than the tick count — "Đã chọn 8 món" alone
  // doesn't tell you whether that means adding 8 or changing nothing.
  const pending = React.useMemo(() => {
    let add = 0;
    let remove = 0;
    for (const i of items) {
      const checked = selected.has(i.id);
      if (checked && !i.linked) add += 1;
      else if (!checked && i.linked) remove += 1;
    }
    return { add, remove };
  }, [items, selected]);

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function handleSave() {
    try {
      const result = await setGroupItems.mutateAsync({
        groupId: group.modifier_group_id,
        input: { item_ids: [...selected] },
      });
      const changed = result.linked.length + result.unlinked.length;
      const failedCount = Object.keys(result.failed ?? {}).length;

      // When every item failed for the same reason, that reason is the
      // story — not the item ids. Grab refusing the whole write surface
      // over a missing PIN listed as "VNITE…: HTTP 403" three times sent
      // the operator hunting for a fault in items that are fine.
      const reasons = new Set(Object.values(result.failed ?? {}));
      const singleReason = reasons.size === 1 ? [...reasons][0] : null;

      if (failedCount > 0) {
        // Partial success is a normal outcome here — Grab is asked once
        // per item. Saying "done" would hide the items that didn't take.
        //
        // The reason has to appear whether or not some items got through:
        // a run where 2 succeeded and 3 hit the PIN gate is the common
        // shape, and it must not be the one case that never says "PIN".
        toast.warning(
          changed === 0
            ? `Không cập nhật được món nào${singleReason ? ` — ${singleReason}` : ""}`
            : `Đã cập nhật ${changed} món, ${failedCount} món không được`,
          {
            description: singleReason
              ? `${failedCount} món đều bị từ chối: ${singleReason}. Không phải do món hay nhóm bạn chọn.`
              : Object.entries(result.failed)
                  .slice(0, 3)
                  .map(([id, why]) => `${id}: ${why}`)
                  .join(" · "),
          },
        );
      } else if (!result.lock_acquired) {
        toast.warning(`Đã cập nhật ${changed} món — Grab không cấp khóa sửa menu`, {
          description:
            "Thay đổi vẫn được gửi, nhưng nếu thấy sai lệch thì thử lại sau ít phút.",
        });
      } else {
        toast.success(
          changed > 0
            ? `Đã cập nhật liên kết cho ${changed} món`
            : "Không có thay đổi nào",
        );
      }
      setOpen(false);
      onSaved?.();
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Cập nhật liên kết thất bại";
      toast.error(msg);
    }
  }

  const saving = setGroupItems.isPending;

  return (
    <>
      <Button
        variant="ghost"
        size="icon"
        className="h-7 w-7 flex-shrink-0"
        onClick={() => setOpen(true)}
        aria-label={`Liên kết ${group.modifier_group_name || "nhóm tùy chọn"} với món`}
        title="Liên kết với món"
      >
        <Link2 className="h-3.5 w-3.5" />
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="flex max-h-[90vh] w-[calc(100vw-2rem)] flex-col overflow-hidden sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Chọn món</DialogTitle>
            <DialogDescription>
              Chọn các món từ thực đơn mà bạn có thể tùy chỉnh{" "}
              <span className="font-medium text-(--color-foreground)">
                {group.modifier_group_name || "(Không tên)"}
              </span>
            </DialogDescription>
          </DialogHeader>

          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Tìm món hoặc danh mục…"
            aria-label="Tìm món"
          />

          <div className="-mx-1 min-h-0 flex-1 space-y-2 overflow-y-auto px-1 py-1">
            {menu.isLoading ? (
              Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-[72px] w-full rounded-xl" />
              ))
            ) : visible.length === 0 ? (
              <p className="py-6 text-center text-sm text-(--color-muted-foreground)">
                {items.length === 0
                  ? "Không đọc được món nào từ thực đơn."
                  : "Không có món nào khớp."}
              </p>
            ) : (
              visible.map((item) => {
                const checked = selected.has(item.id);
                return (
                  <button
                    key={item.id}
                    type="button"
                    role="checkbox"
                    aria-checked={checked}
                    onClick={() => toggle(item.id)}
                    className={cn(
                      "flex w-full items-center gap-3 rounded-xl border p-2 text-left transition-colors",
                      checked
                        ? "border-(--color-brand) bg-(--color-brand)/5"
                        : "border-(--color-border) hover:bg-(--color-surface-3)/40",
                    )}
                  >
                    {/* Plain <img>, matching CategoryCard / ItemImageUploader.
                        next/image would additionally have to satisfy
                        next.config's remotePatterns for whatever CDN host
                        Grab hands back, and a picker row is not worth that. */}
                    <div className="h-14 w-14 flex-shrink-0 overflow-hidden rounded-lg bg-(--color-surface-3)">
                      {item.imageUrl ? (
                        <img
                          src={item.imageUrl}
                          alt=""
                          loading="lazy"
                          className="h-full w-full object-cover"
                        />
                      ) : null}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium text-(--color-foreground)">
                        {item.name}
                      </div>
                      <div className="text-xs text-(--color-muted-foreground)">
                        {formatVnd(item.priceVnd)}
                        {item.categoryName ? ` · ${item.categoryName}` : ""}
                      </div>
                      {/* Three distinct states, because "ticked" alone is
                          ambiguous: it can mean "already linked, leaving it
                          alone" or "about to be linked". The operator needs
                          to see which of their ticks are actually changes. */}
                      {item.linked && checked ? (
                        <div className="mt-0.5 text-[11px] text-(--color-muted-foreground)">
                          Đang liên kết
                        </div>
                      ) : item.linked && !checked ? (
                        <div className="mt-0.5 text-[11px] font-medium text-red-500">
                          Sẽ bỏ liên kết
                        </div>
                      ) : !item.linked && checked ? (
                        <div className="mt-0.5 text-[11px] font-medium text-(--color-brand)">
                          Sẽ liên kết
                        </div>
                      ) : null}
                    </div>
                    <span
                      aria-hidden
                      className={cn(
                        "flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-md border transition-colors",
                        checked
                          ? "border-(--color-brand) bg-(--color-brand) text-white"
                          : "border-(--color-border)",
                      )}
                    >
                      {checked ? <Check className="h-4 w-4" /> : null}
                    </span>
                  </button>
                );
              })
            )}
          </div>

          <div className="space-y-1.5">
            {pending.add > 0 || pending.remove > 0 ? (
              <p className="text-center text-xs text-(--color-muted-foreground)">
                {pending.add > 0 ? `+${pending.add} liên kết` : ""}
                {pending.add > 0 && pending.remove > 0 ? " · " : ""}
                {pending.remove > 0 ? `−${pending.remove} bỏ liên kết` : ""}
              </p>
            ) : null}
            <Button
              onClick={handleSave}
              disabled={saving || menu.isLoading}
              className="w-full rounded-full bg-(--color-brand) py-6 text-base text-white hover:bg-(--color-brand-hover)"
            >
              {saving ? "Đang lưu…" : `Hoàn tất • Đã chọn ${selected.size} món`}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
