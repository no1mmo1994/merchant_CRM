"use client";

import * as React from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Separator } from "@/components/ui/separator";
import { ModifierEditor } from "@/components/modifiers/ModifierEditor";
import { ModifierPickerChip } from "@/components/modifiers/ModifierPickerChip";
import type { PickerModifierOption } from "@/components/modifiers/ModifierPickerChip";
import { useModifierGroups, type ModifierGroup, type ModifierOption } from "@/lib/api/modifiers";
import { ApiError } from "@/lib/api";
import { toast } from "sonner";

/**
 * Convert a backend `ModifierOption` into the shape consumed by
 * `ModifierPickerChip` so the preview panel can render the option
 * chips the same way the menu item editor would.
 */
function toPickerOption(opt: ModifierOption): PickerModifierOption {
  return {
    id: opt.modifier_id,
    name: opt.modifier_name,
    priceVnd: opt.price_vnd,
    available: opt.available_status === 1 || opt.available_status === undefined || opt.available_status === null,
  };
}

/** Format a VND price in `12.000đ` style used by the Grab Merchant app. */
function formatVnd(value: number): string {
  return `${value.toLocaleString("vi-VN")}đ`;
}

export function ModifiersClient() {
  const { data: groups = [], isLoading, error } = useModifierGroups();
  const [pickerSelection, setPickerSelection] = React.useState<Record<string, string[]>>({});

  React.useEffect(() => {
    if (error instanceof ApiError) {
      toast.error(`Không thể tải nhóm tùy chọn: ${error.message}`);
    }
  }, [error]);

  return (
    <div className="grid gap-6 lg:grid-cols-5">
      <div className="lg:col-span-3">
        <ModifierEditor />
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
              groups.map((g: ModifierGroup) => {
                const pickerOpts = g.modifiers.map(toPickerOption);
                const minMax =
                  g.selection_range_min === g.selection_range_max
                    ? `${g.selection_range_max}`
                    : `${g.selection_range_min}–${g.selection_range_max}`;
                return (
                  <div
                    key={g.modifier_group_id || g.modifier_group_name}
                    className="rounded-lg border border-(--color-border) bg-(--color-surface-2) p-3"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="text-sm font-medium text-(--color-foreground)">
                        {g.modifier_group_name || "(Không tên)"}
                      </div>
                      <div className="flex items-center gap-1.5">
                        <Badge variant="outline" className="text-xs">
                          {minMax} lựa chọn
                        </Badge>
                        <Badge variant="secondary" className="text-xs">
                          {g.modifiers.length} món
                        </Badge>
                      </div>
                    </div>

                    {g.modifiers.length > 0 ? (
                      <>
                        <Separator className="my-2" />
                        <div className="space-y-1">
                          {g.modifiers.map((m) => (
                            <div
                              key={m.modifier_id || m.modifier_name}
                              className="flex items-center justify-between gap-2 text-xs"
                            >
                              <span
                                className={
                                  m.available_status === 0
                                    ? "text-(--color-muted-foreground) line-through"
                                    : "text-(--color-foreground)"
                                }
                              >
                                {m.modifier_name || "(Không tên)"}
                              </span>
                              <span className="text-(--color-muted-foreground)">
                                {m.is_need_extra_cost
                                  ? `+${formatVnd(m.price_vnd)}`
                                  : "Miễn phí"}
                              </span>
                            </div>
                          ))}
                        </div>

                        <Separator className="my-2" />
                        <ModifierPickerChip
                          groupName={g.modifier_group_name}
                          options={pickerOpts}
                          multi={g.selection_range_max > 1}
                          value={pickerSelection[g.modifier_group_id] ?? []}
                          onChange={(ids) =>
                            setPickerSelection((prev) => ({
                              ...prev,
                              [g.modifier_group_id]: ids,
                            }))
                          }
                        />
                      </>
                    ) : (
                      <p className="mt-2 text-xs text-(--color-muted-foreground)">
                        Nhóm này hiện chưa có tùy chọn nào.
                      </p>
                    )}
                  </div>
                );
              })
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
