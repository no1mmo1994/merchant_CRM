"use client";

/**
 * Dashboard "Phân tích chi phí" visualization.
 *
 * Replaces the previous `BreakdownTable` (rendered inside
 * ``FinancialReportCard.tsx``) — same data, but bars are the hero
 * element instead of a thin progress meter tacked onto a table cell.
 *
 * Data is pre-computed by the parent (``FinancialReportCard``) so
 * this component is pure presentation: it never reads
 * ``useFinanceSummary`` itself, never recomputes percentages, and
 * never hits the network.
 *
 * Why custom CSS bars instead of ``recharts``?
 *   We have exactly 5 single-value rows with the amount + % already
 *   shown numerically next to the bar. A recharts ``BarChart`` adds
 *   axis config, fixed-height responsive container, and tooltip
 *   wiring for zero information gain. The same `<div>` + inner
 *   `<div>` we already had, widened to ``h-2`` and surfaced as a
 *   leading bar, is the minimal-diff upgrade.
 */

import * as React from "react";
import { cn } from "@/lib/utils";

/** Per-row tone — drives the bar fill colour and the label colour. */
export type BreakdownTone = "warning" | "success" | "muted" | "neutral";

export interface BreakdownRow {
  /** Vietnamese label rendered on the left. */
  label: string;
  /** Absolute amount in VND (minor units = ₫). */
  amount: number;
  /** Percentage of the reference revenue (0–100). Pre-computed. */
  pct: number;
  /** Colour tone. */
  tone: BreakdownTone;
}

export interface BreakdownChartProps {
  /** Total reference revenue in VND. Used for the empty-state hint. */
  referenceRevenue: number;
  /** Ordered rows — costs first, take-home last. */
  rows: BreakdownRow[];
}

const BAR_TONE_CLASS: Record<BreakdownTone, string> = {
  warning: "bg-amber-500/70",
  success: "bg-emerald-500/70",
  muted: "bg-zinc-400/60",
  neutral: "bg-(--color-brand)/70",
};

const LABEL_TONE_CLASS: Record<BreakdownTone, string> = {
  warning: "text-(--color-foreground)",
  success: "text-emerald-700",
  muted: "text-(--color-muted-foreground)",
  neutral: "text-(--color-foreground)",
};

/** Format a VND integer with the vi-VN locale + trailing ₫. */
function fmtVnd(value: number): string {
  if (!Number.isFinite(value)) return "— ₫";
  if (value === 0) return "0 ₫";
  return `${value.toLocaleString("vi-VN")} ₫`;
}

/**
 * One row: label · bar · amount · %.
 *
 * Layout is a single CSS grid so the bar's left edge always aligns
 * with the label column, regardless of label width.
 */
function BreakdownRowView({ row }: { row: BreakdownRow }) {
  // Cap rendered width at 100% — a 24.5% row should fill a quarter of
  // the bar zone, not spill over because pct happens to be >100 due
  // to a negative or zero reference revenue.
  const widthPct = Math.min(100, Math.max(0, row.pct));

  return (
    <div className="grid grid-cols-[minmax(7rem,1fr)_2fr_auto_auto] items-center gap-x-3 px-4 py-2.5">
      {/* Label */}
      <span
        className={cn(
          "truncate text-sm font-medium",
          LABEL_TONE_CLASS[row.tone],
        )}
        title={row.label}
      >
        {row.label}
      </span>

      {/* Bar — the hero element. h-2 vs the table's h-1.5 gives it
          real visual weight without dominating the row. */}
      <div className="h-2 w-full overflow-hidden rounded-full bg-(--color-surface-2)">
        <div
          className={cn(
            "h-full transition-all",
            BAR_TONE_CLASS[row.tone],
          )}
          style={{ width: `${widthPct}%` }}
          aria-label={`${row.pct.toFixed(2)}%`}
        />
      </div>

      {/* Amount */}
      <span className="min-w-[7rem] text-right tabular-nums text-sm text-(--color-foreground)">
        {fmtVnd(row.amount)}
      </span>

      {/* % — trailing label so the eye sweeps label → bar → amount → % */}
      <span className="min-w-[4.5rem] text-right tabular-nums text-xs text-(--color-muted-foreground)">
        {row.pct.toFixed(2)}%
      </span>
    </div>
  );
}

export function BreakdownChart({
  referenceRevenue,
  rows,
}: BreakdownChartProps) {
  return (
    <div className="overflow-hidden rounded-xl border border-(--color-border)">
      <div className="border-b border-(--color-border) bg-(--color-surface-2)/40 px-4 py-2.5 text-xs font-medium uppercase tracking-wide text-(--color-muted-foreground)">
        Phân tích chi phí (% theo Doanh thu)
      </div>
      <div className="divide-y divide-(--color-border)/60">
        {rows.map((row) => (
          <BreakdownRowView key={row.label} row={row} />
        ))}
      </div>
      {referenceRevenue === 0 && (
        <div className="border-t border-(--color-border) bg-(--color-surface-2)/40 px-4 py-2 text-xs text-(--color-muted-foreground)">
          Chưa có doanh thu trong khoảng đã chọn — phần trăm hiển thị 0%.
        </div>
      )}
    </div>
  );
}