"use client";

import * as React from "react";
import { Coins, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/**
 * Date-range picker shared by the dashboard "Tổng quan" report and the
 * Finance page. Identical UX (Từ ngày / Đến ngày / Áp dụng + currency
 * badge showing the applied range) — extracted from
 * ``finance-client.tsx`` so both pages stop duplicating the same 50
 * lines.
 *
 * Controlled component: parent owns the strings and is responsible
 * for applying them to the data hook on submit. This lets the
 * Finance page batch a single ``useFinanceSummary`` call on Apply
 * instead of re-fetching every keystroke.
 *
 * The picker is intentionally narrow: two ``<input type="date">``s,
 * an Apply button with a spinner, and a small status line on the
 * right. Anything more elaborate (presets, picker dialog, time
 * ranges) belongs in a future iteration.
 */
export interface DateRangePickerProps {
  /** Current "Từ ngày" value, ISO YYYY-MM-DD. */
  from: string;
  /** Current "Đến ngày" value, ISO YYYY-MM-DD. */
  to: string;
  /** True while the parent's data hook is fetching. */
  isLoading?: boolean;
  /**
   * Optional "applied range + currency" footer string shown on the
   * right side. Pass the formatted ``"Đang xem: 2026-08-01 →
   * 2026-08-06 [VND]"`` block the Finance page uses, or omit for
   * the simpler loading text.
   */
  footer?: React.ReactNode;
  /** Called on every input change. Parent should update its state. */
  onFromChange: (next: string) => void;
  onToChange: (next: string) => void;
  /** Called when the user submits the form (Enter or Áp dụng). */
  onApply: () => void;
}

export function DateRangePicker({
  from,
  to,
  isLoading = false,
  footer,
  onFromChange,
  onToChange,
  onApply,
}: DateRangePickerProps) {
  return (
    <form
      className="flex flex-wrap items-end gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        onApply();
      }}
    >
      <label className="flex flex-col gap-1 text-xs text-(--color-muted-foreground)">
        Từ ngày
        <Input
          type="date"
          value={from}
          onChange={(e) => onFromChange(e.target.value)}
          max={to || undefined}
          className="w-[170px]"
        />
      </label>
      <label className="flex flex-col gap-1 text-xs text-(--color-muted-foreground)">
        Đến ngày
        <Input
          type="date"
          value={to}
          onChange={(e) => onToChange(e.target.value)}
          min={from || undefined}
          className="w-[170px]"
        />
      </label>
      <Button type="submit" disabled={isLoading} className="gap-1.5">
        {isLoading ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        ) : (
          <Coins className="h-3.5 w-3.5" />
        )}
        Áp dụng
      </Button>
      <div className="ml-auto text-xs text-(--color-muted-foreground)">
        {footer ?? <span>Đang đồng bộ từ Grab…</span>}
      </div>
    </form>
  );
}

/**
 * Default range = last 7 days inclusive.
 *
 * Mirrors ``defaultRange`` in ``finance-client.tsx`` so the dashboard
 * "Tổng quan" report and the Finance page both start on the same
 * preset. Defined here (rather than in each consumer) so adding a
 * preset dropdown in future means changing one file.
 */
export function defaultDateRange(): { from: string; to: string } {
  const today = new Date();
  const start = new Date(today);
  start.setDate(start.getDate() - 6);
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  return { from: iso(start), to: iso(today) };
}