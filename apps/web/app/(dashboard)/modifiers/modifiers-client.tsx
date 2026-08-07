"use client";

import * as React from "react";
import { AlertTriangle, ChevronDown, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { ModifierEditor } from "@/components/modifiers/ModifierEditor";
import { EditModifierGroupDialog } from "@/components/modifiers/EditModifierGroupDialog";
import {
  listModifierGroupsRaw,
  useDeleteModifierGroup,
  type ModifierGroup,
  type ModifierOption,
  type ListModifierGroupsResponse,
} from "@/lib/api/modifiers";
import { ApiError } from "@/lib/api";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

/** Format a VND price in `12.000đ` style used by the Grab Merchant app. */
function formatVnd(value: number): string {
  return `${value.toLocaleString("vi-VN")}đ`;
}

interface GroupCardProps {
  group: ModifierGroup;
  /** Re-fetch the list after this group was edited or deleted. */
  onChanged?: () => void;
}

/**
 * Collapsible group card. Header shows the group name, the actual
 * linked-item count (previously always 0 — now the backend walks the
 * menu tree), and the categories this group is attached to
 * (replaces the meaningless "Nguồn: menu_fallback" badge).
 *
 * Click to expand the list of modifier rows; each row has an
 * availability toggle. Edit and delete live in the header, to the left
 * of the chevron.
 *
 * The header used to be one big `<button>` wrapping everything. It is
 * now a flex row: the disclosure `<button>` covers the text block and
 * the chevron, and the action buttons sit beside it as siblings. Nesting
 * them inside the disclosure button would be invalid HTML and breaks
 * hydration — `CategoryCard` solves it the same way.
 */
function GroupCard({ group, onChanged }: GroupCardProps) {
  const [open, setOpen] = React.useState(false);
  const bodyId = React.useId();
  const linkedCategories = group.linked_categories ?? [];
  const showCategories = linkedCategories.length > 0;
  const deleteGroup = useDeleteModifierGroup();

  async function handleDelete() {
    const name = group.modifier_group_name || "(Không tên)";
    const linked = group.linked_item_count ?? 0;
    // No AlertDialog in this repo — destructive confirms are native,
    // matching CategoryCard / settings-client. Spell out the blast
    // radius: Grab lets you delete a group that items still use, and
    // those items silently lose it.
    const warning =
      linked > 0
        ? `\n\n${linked} món đang dùng nhóm này sẽ mất nhóm.`
        : "";
    if (!confirm(`Xóa nhóm tùy chọn "${name}"?${warning}\n\nThao tác này không thể hoàn tác.`)) {
      return;
    }
    try {
      await deleteGroup.mutateAsync(group.modifier_group_id);
      toast.success(`Đã xóa "${name}"`);
      onChanged?.();
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Xóa nhóm tùy chọn thất bại";
      toast.error(msg);
    }
  }

  return (
    <div className="overflow-hidden rounded-lg border border-(--color-border) bg-(--color-surface-2)">
      <div className="flex items-center gap-1 pr-2 transition-colors hover:bg-(--color-surface-3)/40">
        <button
          type="button"
          aria-expanded={open}
          aria-controls={bodyId}
          onClick={() => setOpen((v) => !v)}
          className="flex min-w-0 flex-1 items-center justify-between gap-2 p-4 text-left"
        >
          <div className="min-w-0">
            <div className="truncate text-sm font-medium text-(--color-foreground)">
              {group.modifier_group_name || "(Không tên)"}
            </div>
            <div className="mt-0.5 text-xs text-(--color-muted-foreground)">
              Liên kết với {group.linked_item_count ?? 0} món
            </div>
            {showCategories && (
              <div
                className="mt-1 flex flex-wrap gap-1 text-[11px] text-(--color-muted-foreground)"
                title={linkedCategories
                  .map((c) => `${c.category_name || "(không tên)"} (${c.category_id}) · ${c.item_count} món`)
                  .join("\n")}
              >
                <span>Thuộc:</span>
                {linkedCategories.map((c) => (
                  <span
                    key={c.category_id || c.category_name}
                    className="rounded bg-(--color-brand)/10 px-1.5 py-0.5 font-mono text-[10px] text-(--color-brand)"
                  >
                    {c.category_name || "(không tên)"}
                    {c.category_id ? ` · ${c.category_id}` : ""}
                    {c.item_count > 0 ? ` · ${c.item_count} món` : ""}
                  </span>
                ))}
              </div>
            )}
          </div>
          <ChevronDown
            className={cn(
              "h-4 w-4 shrink-0 text-(--color-muted-foreground) transition-transform",
              open && "rotate-180",
            )}
          />
        </button>
        <EditModifierGroupDialog group={group} onSaved={onChanged} />
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 flex-shrink-0 text-red-500 hover:bg-red-500/10 hover:text-red-500"
          onClick={handleDelete}
          disabled={deleteGroup.isPending}
          aria-label={`Xóa ${group.modifier_group_name || "nhóm tùy chọn"}`}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      </div>
      {open && (
        <div id={bodyId} className="border-t border-(--color-border) bg-(--color-background)">
          {group.modifiers.length === 0 ? (
            <p className="px-4 py-3 text-xs text-(--color-muted-foreground)">
              Nhóm này hiện chưa có tùy chọn nào.
            </p>
          ) : (
            <ul className="divide-y divide-(--color-border)">
              {group.modifiers.map((m: ModifierOption) => (
                <ModifierRow key={m.modifier_id || m.modifier_name} modifier={m} />
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

interface ModifierRowProps {
  modifier: ModifierOption;
}

/**
 * Single modifier row: name + price on the left, availability
 * toggle on the right. Availability defaults to true when Grab
 * doesn't report an explicit status.
 */
function ModifierRow({ modifier }: ModifierRowProps) {
  // available_status: 1 = available, 0 = unavailable. Treat null/undefined as available.
  const initial = modifier.available_status !== 0;
  const [available, setAvailable] = React.useState(initial);

  // Sync if the upstream data changes (e.g. after a reload).
  React.useEffect(() => {
    setAvailable(modifier.available_status !== 0);
  }, [modifier.available_status, modifier.modifier_id]);

  return (
    <li className="flex items-center justify-between gap-3 px-4 py-3">
      <div className="min-w-0">
        <div
          className={cn(
            "truncate text-sm",
            available ? "text-(--color-foreground)" : "text-(--color-muted-foreground) line-through",
          )}
        >
          {modifier.modifier_name || "(Không tên)"}
        </div>
        <div className="mt-0.5 text-xs text-(--color-muted-foreground)">
          {modifier.is_need_extra_cost ? formatVnd(modifier.price_vnd) : "Miễn phí"}
        </div>
      </div>
      <Switch
        checked={available}
        onCheckedChange={setAvailable}
        aria-label={`Bật/tắt ${modifier.modifier_name || "tùy chọn"}`}
      />
    </li>
  );
}

export function ModifiersClient() {
  const [groups, setGroups] = React.useState<ModifierGroup[]>([]);
  const [partial, setPartial] = React.useState(false);
  const [source, setSource] = React.useState<"direct" | "menu_fallback" | "empty" | null>(null);
  const [isLoading, setIsLoading] = React.useState(true);
  const [error, setError] = React.useState<unknown>(null);

  const reload = React.useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res: ListModifierGroupsResponse = await listModifierGroupsRaw();
      setGroups(res.modifier_groups ?? []);
      setPartial(res.partial ?? false);
      setSource(res.source ?? "direct");
    } catch (err) {
      setError(err);
      setGroups([]);
      setPartial(false);
      setSource(null);
    } finally {
      setIsLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void reload();
  }, [reload]);

  React.useEffect(() => {
    if (error instanceof ApiError) {
      toast.error(`Không thể tải nhóm tùy chọn: ${error.message}`);
    }
  }, [error]);

  return (
    <div className="grid gap-6 lg:grid-cols-5">
      <div className="lg:col-span-3">
        <ModifierEditor onCreated={() => void reload()} />
      </div>
      <div className="space-y-4 lg:col-span-2">
        <Card className="border-(--color-border)">
          <CardHeader>
            <div className="flex items-center justify-between gap-2">
              <CardTitle>Nhóm tùy chọn đang có</CardTitle>
              <Badge variant="secondary">{groups.length}</Badge>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            {partial && (
              <div className="flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-50/50 p-2.5 text-xs text-amber-800">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <span>
                  Grab tạm thời không trả được danh sách nhóm tùy chọn — hiển thị
                  dữ liệu lấy từ thực đơn. Có thể thiếu nhóm chưa gắn vào món nào.
                </span>
              </div>
            )}
            {isLoading ? (
              <div className="space-y-2">
                {[0, 1, 2].map((i) => (
                  <Skeleton key={i} className="h-14 w-full" />
                ))}
              </div>
            ) : groups.length === 0 ? (
              <div className="rounded-lg border border-dashed border-(--color-border) p-6 text-center text-sm text-(--color-muted-foreground)">
                Chưa có nhóm nào. Tạo một nhóm bên trái hoặc đồng bộ từ Grab.
              </div>
            ) : (
              <div className="space-y-2">
                {groups.map((g) => (
                  <GroupCard
                    key={g.modifier_group_id || g.modifier_group_name}
                    group={g}
                    // This page keeps its own `reload()` instead of the
                    // React Query cache (it needs `partial`/`source`,
                    // which useModifierGroups drops), so mutations must
                    // refresh it explicitly — same wiring as
                    // ModifierEditor's `onCreated` below.
                    onChanged={() => void reload()}
                  />
                ))}
              </div>
            )}
            {/* The previous "Nguồn: menu_fallback" tag was redundant with the
                amber partial banner above and didn't tell the merchant
                anything actionable. Category info now lives on each group
                card ("Thuộc: <CategoryName> (<CategoryID>)"), so we
                don't need a separate source line here. */}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}