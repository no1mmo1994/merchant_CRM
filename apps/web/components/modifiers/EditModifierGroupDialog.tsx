"use client";

import * as React from "react";
import { Pencil, Plus, Trash2 } from "lucide-react";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api";
import {
  useUpdateModifierGroup,
  type ModifierGroup,
  type ModifierSpec,
} from "@/lib/api/modifiers";

/**
 * One editable row in the options repeater.
 *
 * `key` is a client-only handle so React can track rows across
 * add/remove — it must NOT be sent to the server. `modifierId` is Grab's
 * id and is the load-bearing field: it is "" for a row the operator just
 * added, and the original id for one that already existed. Sending it
 * back unchanged is what makes Grab edit the option in place instead of
 * deleting it and minting a new id.
 */
type OptionRow = {
  key: string;
  modifierId: string;
  name: string;
  priceVnd: number;
};

function rowsFromGroup(group: ModifierGroup): OptionRow[] {
  const rows = group.modifiers.map((m, i) => ({
    key: `existing-${m.modifier_id || i}`,
    modifierId: m.modifier_id ?? "",
    name: m.modifier_name ?? "",
    priceVnd: m.price_vnd ?? 0,
  }));
  // A group with no options can't be saved (Grab rejects an empty
  // `modifiers` array), so seed one blank row to edit rather than
  // showing a dead form.
  return rows.length > 0
    ? rows
    : [{ key: "new-0", modifierId: "", name: "", priceVnd: 0 }];
}

export function EditModifierGroupDialog({
  group,
  onSaved,
}: {
  group: ModifierGroup;
  onSaved?: () => void;
}) {
  const [open, setOpen] = React.useState(false);
  const updateGroup = useUpdateModifierGroup();

  const [name, setName] = React.useState(group.modifier_group_name);
  const [min, setMin] = React.useState(group.selection_range_min);
  const [max, setMax] = React.useState(group.selection_range_max);
  const [rows, setRows] = React.useState<OptionRow[]>(() => rowsFromGroup(group));
  const nextKey = React.useRef(0);

  // Re-seed from props only when the dialog opens. Doing it on every
  // `group` change would clobber half-typed edits whenever a background
  // refetch lands mid-edit — the same trap EditItemDialog documents.
  React.useEffect(() => {
    if (!open) return;
    setName(group.modifier_group_name);
    setMin(group.selection_range_min);
    setMax(group.selection_range_max);
    setRows(rowsFromGroup(group));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const trimmedRows = rows.map((r) => ({ ...r, name: r.name.trim() }));
  const error =
    !name.trim()
      ? "Bắt buộc nhập tên nhóm"
      : trimmedRows.length === 0
        ? "Thêm ít nhất một tùy chọn"
        : trimmedRows.some((r) => !r.name)
          ? "Mọi tùy chọn đều phải có tên"
          : trimmedRows.some((r) => !Number.isFinite(r.priceVnd) || r.priceVnd < 0)
            ? "Giá phải ≥ 0"
            : max < min
              ? "Chọn tối đa phải ≥ chọn tối thiểu"
              : // Grab enforces this server-side and reports it as a 409
                // whose `reason` reads "already_exists" — indistinguishable
                // from a name clash unless you read `target: InvalidRange`.
                // Catching it here shows the operator the real cause, on the
                // real field, before the request is even sent.
                max > trimmedRows.length
                ? `Chọn tối đa (${max}) không được lớn hơn số tùy chọn (${trimmedRows.length})`
                : null;

  async function handleSave() {
    if (error) return;
    const modifiers: ModifierSpec[] = trimmedRows.map((r) => ({
      name: r.name,
      price_vnd: Math.trunc(r.priceVnd),
      // Only send a non-empty id — omitting it entirely for new rows
      // keeps the payload identical to what create sends.
      ...(r.modifierId ? { modifier_id: r.modifierId } : {}),
    }));
    try {
      const result = await updateGroup.mutateAsync({
        groupId: group.modifier_group_id,
        input: {
          group_name: name.trim(),
          selection_range_min: min,
          selection_range_max: max,
          modifiers,
        },
      });
      // `verified === false` means the write landed but the server could
      // not check whether Grab edited in place or quietly made a copy.
      // Saying "Đã cập nhật" alone would overstate what we know, so ask
      // the operator to eyeball the list.
      if (result?.verified === false) {
        toast.warning(`Đã lưu "${name.trim()}" — chưa xác minh được`, {
          description:
            "Không đọc được danh sách nhóm để đối chiếu. Kiểm tra lại xem có nhóm trùng tên vừa xuất hiện không.",
        });
      } else {
        toast.success(`Đã cập nhật "${name.trim()}"`);
      }
      setOpen(false);
      onSaved?.();
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Cập nhật nhóm tùy chọn thất bại";
      toast.error(msg);
    }
  }

  const saving = updateGroup.isPending;

  return (
    <>
      <Button
        variant="ghost"
        size="icon"
        className="h-7 w-7 flex-shrink-0"
        onClick={() => setOpen(true)}
        aria-label={`Chỉnh sửa ${group.modifier_group_name || "nhóm tùy chọn"}`}
      >
        <Pencil className="h-3.5 w-3.5" />
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[90vh] w-[calc(100vw-2rem)] overflow-y-auto sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Chỉnh sửa nhóm tùy chọn</DialogTitle>
            <DialogDescription>
              Cập nhật tên, số lượng chọn và các tùy chọn bên trong. Thay đổi
              được ghi trực tiếp lên Grab.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="mg-name">Tên nhóm (tiếng Việt)</Label>
              <Input
                id="mg-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Kích thước, Topping, Mức đường…"
                maxLength={80}
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="mg-min">Chọn tối thiểu</Label>
                <Input
                  id="mg-min"
                  type="number"
                  min={0}
                  value={min}
                  onChange={(e) => setMin(Number(e.target.value))}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="mg-max">Chọn tối đa</Label>
                <Input
                  id="mg-max"
                  type="number"
                  min={1}
                  value={max}
                  onChange={(e) => setMax(Number(e.target.value))}
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label>Các tùy chọn</Label>
              {rows.map((row, idx) => (
                <div key={row.key} className="flex items-start gap-2">
                  <Input
                    value={row.name}
                    onChange={(e) =>
                      setRows((prev) =>
                        prev.map((r, i) =>
                          i === idx ? { ...r, name: e.target.value } : r,
                        ),
                      )
                    }
                    placeholder="Tên tùy chọn (ví dụ: Lớn)"
                    className="flex-1"
                  />
                  <Input
                    type="number"
                    min={0}
                    value={row.priceVnd}
                    onChange={(e) =>
                      setRows((prev) =>
                        prev.map((r, i) =>
                          i === idx ? { ...r, priceVnd: Number(e.target.value) } : r,
                        ),
                      )
                    }
                    placeholder="Giá (đ)"
                    className="w-28"
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    onClick={() => {
                      const next = rows.filter((_, i) => i !== idx);
                      // Grab rejects a group whose selection window doesn't
                      // fit its option list, with a 409 whose `reason`
                      // misleadingly reads "already_exists". Removing an
                      // option is the usual way to trip it, so pull the
                      // window down with the list rather than letting the
                      // operator discover it on save.
                      //
                      // Both bounds, not just the ceiling: clamping `max`
                      // alone can drive it below an untouched `min` (min 3,
                      // max 5, delete down to 2 options → max 2 < min 3) and
                      // strand the form on "Chọn tối đa phải ≥ chọn tối
                      // thiểu", which names no numbers and no way out.
                      //
                      // Kept as three sibling setters instead of nesting
                      // them inside setRows' updater — updater functions
                      // must be pure, and StrictMode double-invokes them.
                      setRows(next);
                      setMax((m) => Math.min(m, next.length));
                      setMin((mn) => Math.min(mn, next.length));
                    }}
                    disabled={rows.length <= 1}
                    aria-label="Xóa tùy chọn"
                    className="text-red-500 hover:bg-red-500/10 hover:text-red-500"
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              ))}
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() =>
                  setRows((prev) => [
                    ...prev,
                    {
                      key: `new-${(nextKey.current += 1)}`,
                      modifierId: "",
                      name: "",
                      priceVnd: 0,
                    },
                  ])
                }
              >
                <Plus className="mr-1 h-3.5 w-3.5" />
                Thêm tùy chọn
              </Button>
            </div>

            {error ? <p className="text-xs text-red-500">{error}</p> : null}
          </div>

          <DialogFooter className="-mx-4 -mb-4 mt-2">
            <Button variant="ghost" onClick={() => setOpen(false)} disabled={saving}>
              Hủy
            </Button>
            <Button
              onClick={handleSave}
              disabled={saving || error !== null}
              className="bg-(--color-brand) text-white hover:bg-(--color-brand-hover)"
            >
              {saving ? "Đang lưu…" : "Lưu thay đổi"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
