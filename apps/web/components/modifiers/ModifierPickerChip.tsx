"use client";

import * as React from "react";
import { X } from "lucide-react";
import { Badge } from "@/components/ui/badge";

export interface PickerModifierOption {
  id: string;
  name: string;
  price_vnd: number;
}

interface ModifierPickerChipProps {
  groupName: string;
  options: PickerModifierOption[];
  /** For single-select groups, set this to true (max = 1). */
  multi?: boolean;
  value: string[];
  onChange: (ids: string[]) => void;
}

function formatVnd(v: number): string {
  return new Intl.NumberFormat("vi-VN").format(v) + " ₫";
}

/**
 * Visual chip-style multi/single picker for selecting modifiers on a menu
 * item. Used by NewItemDialog (via MenuTree's "Quick add") and item detail
 * screens.
 */
export function ModifierPickerChip({
  groupName,
  options,
  multi = true,
  value,
  onChange,
}: ModifierPickerChipProps) {
  function toggle(id: string) {
    if (multi) {
      onChange(value.includes(id) ? value.filter((v) => v !== id) : [...value, id]);
    } else {
      onChange(value.includes(id) ? [] : [id]);
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div className="text-sm font-medium text-(--color-foreground)">{groupName}</div>
        {value.length > 0 && (
          <button
            type="button"
            onClick={() => onChange([])}
            className="inline-flex items-center gap-1 text-xs text-(--color-muted-foreground) hover:text-(--color-foreground)"
          >
            <X className="h-3 w-3" />
            Clear
          </button>
        )}
      </div>
      <div className="flex flex-wrap gap-2">
        {options.map((opt) => {
          const active = value.includes(opt.id);
          return (
            <button
              key={opt.id}
              type="button"
              onClick={() => toggle(opt.id)}
              className={[
                "inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm transition-colors",
                active
                  ? "border-(--color-brand) bg-(--color-brand)/10 text-(--color-brand)"
                  : "border-(--color-border) bg-(--color-surface) text-(--color-foreground) hover:bg-(--color-surface-2)",
              ].join(" ")}
            >
              <span>{opt.name}</span>
              {opt.price_vnd > 0 && (
                <span className="text-xs text-(--color-muted-foreground)">
                  +{formatVnd(opt.price_vnd)}
                </span>
              )}
              {active && <Badge variant="default" className="bg-(--color-brand) text-white">✓</Badge>}
            </button>
          );
        })}
        {options.length === 0 && (
          <div className="text-xs text-(--color-muted-foreground)">No options in this group.</div>
        )}
      </div>
    </div>
  );
}
