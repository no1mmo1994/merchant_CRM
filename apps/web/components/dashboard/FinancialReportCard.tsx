"use client";

/**
 * Dashboard "Tổng quan" financial report.
 *
 * Surfaces the same `useFinanceSummary` data the /finance page uses,
 * but compressed into a single Metalic.io-style card with the four
 * KPIs the operator asked for verbatim:
 *
 *   - Tổng đơn
 *   - Doanh thu
 *   - Chiết khấu nền tảng
 *   - Số tiền thực nhận (Thu nhập ròng)
 *
 * …plus a 4-tile secondary row (VAT / PIT / Doanh thu ròng /
 * Marketing) and a percentage breakdown table that answers the
 * operator's "các khoản chiếm bao nhiêu %" question.
 *
 * Notes:
 *
 * - "Số tiền thực nhận" maps to ``earnings_balance`` (top-level Grab
 *   field, already net of every deduction / tax / commission).
 *   ``Thu nhập ròng`` was reserved in ``_METRIC_ORDER`` but never
 *   gets filled because no English Grab label maps to it. We use
 *   the top-level balance instead — it's the actual payout figure
 *   the operator sees in the merchant app.
 *
 * - Marketing cost is reported as ``0 ₫`` with a hint. Grab's
 *   ``uiBreakdown`` mixes platform commission and marketing fees
 *   into the same ``Deduction`` accordion, and the current router
 *   walker (``_walk``) sums both into the "Khấu trừ" bucket without
 *   splitting. Surfacing an honest "0 ₫" + explanation beats
 *   guessing a split.
 *
 * - Date picker is the shared ``DateRangePicker`` — same UX as the
 *   /finance page so the operator doesn't relearn anything.
 */

import * as React from "react";
import {
  AlertCircle,
  Banknote,
  CalendarRange,
  Coins,
  CreditCard,
  Loader2,
  Percent,
  Receipt,
  TrendingDown,
  TrendingUp,
  Wallet,
} from "lucide-react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useFinanceSummary,
  type FinancialMetricGroup,
} from "@/lib/api/finance";
import { DateRangePicker, defaultDateRange } from "./DateRangePicker";
import { BreakdownChart, type BreakdownRow } from "./BreakdownChart";
import { cn } from "@/lib/utils";

/** Locale formatter — mirrors `formatVnd` in finance-client.tsx. */
function fmtVnd(value: number): string {
  if (!Number.isFinite(value)) return "— ₫";
  if (value === 0) return "0 ₫";
  return `${value.toLocaleString("vi-VN")} ₫`;
}

/** Lookup the first numeric value for a Vietnamese-labelled metric. */
function firstValueFor(
  metrics: FinancialMetricGroup[],
  label: string,
): number | null {
  const group = metrics.find((m) => m.label === label);
  if (!group || group.values.length === 0) return null;
  return group.values[0]?.value_minor ?? null;
}

/** Compute pct = |cost| / |revenue| * 100. Returns 0 when revenue is 0. */
function pctOf(cost: number, revenue: number): number {
  if (!revenue) return 0;
  return (Math.abs(cost) / Math.abs(revenue)) * 100;
}

/**
 * The four primary KPI tiles + four secondary tiles + breakdown table.
 *
 * Rendered as a single dashboard section (full-width) instead of the
 * previous 4 placeholder ``StatCard``s — the operator asked for a
 * single integrated report, not four scattered numbers.
 */
export function FinancialReportCard() {
  const initial = React.useMemo(defaultDateRange, []);
  const [from, setFrom] = React.useState<string>(initial.from);
  const [to, setTo] = React.useState<string>(initial.to);
  const [appliedFrom, setAppliedFrom] = React.useState<string>(initial.from);
  const [appliedTo, setAppliedTo] = React.useState<string>(initial.to);

  const query = useFinanceSummary(appliedFrom, appliedTo);
  const data = query.data;
  const isLoading = query.isLoading;
  const isError = !!query.error;

  const applyRange = React.useCallback(() => {
    if (!from || !to) return;
    if (from > to) return;
    setAppliedFrom(from);
    setAppliedTo(to);
  }, [from, to]);

  const refresh = React.useCallback(() => {
    if (from && to && from <= to) {
      setAppliedFrom(from);
      setAppliedTo(to);
    }
    void query.refetch();
  }, [from, to, query]);

  const metrics = data?.metrics ?? [];
  const doanhThu = firstValueFor(metrics, "Doanh thu");
  const khauTru = firstValueFor(metrics, "Khấu trừ");
  const thueGTGT = firstValueFor(metrics, "Thuế GTGT");
  const thueTNCN = firstValueFor(metrics, "Thuế TNCN");
  const doanhThuRong = firstValueFor(metrics, "Doanh thu ròng");
  const earningsBalance = data?.earnings_balance?.value_minor ?? null;
  const totalOrders = data?.total_orders ?? 0;

  // Reference value for the breakdown percentages: gross sales. If
  // Grab doesn't return a Doanh thu (rare, but possible on empty
  // days) fall back to the sales_balance top-level field.
  const referenceRevenue = doanhThu ?? data?.sales_balance?.value_minor ?? 0;

  return (
    <Card className="col-span-12 border-(--color-border)">
      <CardHeader className="flex flex-row items-start justify-between space-y-0 pb-3">
        <div className="space-y-1">
          <CardTitle className="flex items-center gap-2 text-base font-semibold">
            <Wallet className="h-4 w-4 text-(--color-brand)" />
            Báo cáo tài chính
          </CardTitle>
          <p className="text-xs text-(--color-muted-foreground)">
            Tổng đơn, doanh thu, chiết khấu, VAT và số tiền thực nhận trong khoảng đã chọn.
          </p>
        </div>
        <button
          type="button"
          onClick={refresh}
          disabled={query.isFetching}
          className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-(--color-muted-foreground) hover:bg-(--color-surface-2) disabled:opacity-50"
          title="Tải lại"
        >
          <Loader2
            className={cn(
              "h-3.5 w-3.5",
              query.isFetching && "animate-spin",
            )}
          />
          Làm mới
        </button>
      </CardHeader>

      <CardContent className="space-y-6">
        {/* Date range — shared picker used by /finance */}
        <DateRangePicker
          from={from}
          to={to}
          isLoading={query.isFetching}
          onFromChange={setFrom}
          onToChange={setTo}
          onApply={applyRange}
          footer={
            data?.date_range ? (
              <>
                Đang xem:{" "}
                <span className="font-mono">{data.date_range.from}</span> →{" "}
                <span className="font-mono">{data.date_range.to}</span>{" "}
                <span className="ml-1 rounded bg-(--color-surface-2) px-1.5 py-0.5 uppercase">
                  {data.currency || "VND"}
                </span>
              </>
            ) : undefined
          }
        />

        {isError ? (
          <ErrorBanner />
        ) : isLoading && !data ? (
          <SkeletonGrid />
        ) : (
          <>
            {/* Primary KPI row — 4 tiles, Metalic.io style */}
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <PrimaryTile
                icon={<CreditCard className="h-4 w-4" />}
                label="Tổng đơn"
                value={totalOrders.toLocaleString("vi-VN")}
                hint="Số đơn đã lưu trong khoảng"
              />
              <PrimaryTile
                icon={<Banknote className="h-4 w-4" />}
                label="Doanh thu"
                value={fmtVnd(doanhThu ?? 0)}
                tone="brand"
                hint={data?.sales_balance?.display ?? undefined}
              />
              <PrimaryTile
                icon={<TrendingDown className="h-4 w-4" />}
                label="Chiết khấu nền tảng"
                value={fmtVnd(khauTru ?? 0)}
                tone="warning"
                hint="Grab thu từ merchant"
              />
              <PrimaryTile
                icon={<Wallet className="h-4 w-4" />}
                label="Số tiền thực nhận"
                value={
                  earningsBalance != null
                    ? fmtVnd(earningsBalance)
                    : "— ₫"
                }
                tone="success"
                hint="Sau thuế + chiết khấu"
              />
            </div>

            {/* Secondary KPI row — narrower tiles */}
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <SecondaryTile
                icon={<Receipt className="h-4 w-4" />}
                label="VAT đã đóng"
                value={fmtVnd(thueGTGT ?? 0)}
                tone="warning"
              />
              <SecondaryTile
                icon={<Receipt className="h-4 w-4" />}
                label="Thuế TNCN (PIT)"
                value={fmtVnd(thueTNCN ?? 0)}
                tone="warning"
              />
              <SecondaryTile
                icon={<Coins className="h-4 w-4" />}
                label="Doanh thu ròng"
                value={fmtVnd(doanhThuRong ?? 0)}
              />
              <SecondaryTile
                icon={<Percent className="h-4 w-4" />}
                label="Marketing"
                value="0 ₫"
                tone="default"
                hint="Chưa tách được từ Khấu trừ — Grab trả lẫn vào Deduction"
              />
            </div>

            {/* Breakdown chart — answers the operator's "% of revenue"
                question directly. The bar is the hero element; the
                label · amount · % live on the same horizontal axis
                so the eye sweeps left → right in one read. */}
            <BreakdownChart
              referenceRevenue={referenceRevenue}
              rows={buildBreakdownRows({
                referenceRevenue,
                khauTru: khauTru ?? 0,
                thueGTGT: thueGTGT ?? 0,
                thueTNCN: thueTNCN ?? 0,
                marketing: 0,
                earnings: earningsBalance ?? 0,
              })}
            />

            {data?.warnings && data.warnings.length > 0 && (
              <ul className="space-y-1 text-xs text-(--color-muted-foreground)">
                {data.warnings.map((w) => (
                  <li key={w}>• {w}</li>
                ))}
              </ul>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

// ─── Subcomponents ───────────────────────────────────────────────────────────

interface PrimaryTileProps {
  icon: React.ReactNode;
  label: string;
  value: string;
  hint?: string;
  tone?: "brand" | "default" | "warning" | "success";
}

const PRIMARY_TONE: Record<NonNullable<PrimaryTileProps["tone"]>, string> = {
  brand: "text-(--color-brand)",
  default: "text-(--color-foreground)",
  warning: "text-amber-600",
  success: "text-emerald-600",
};

function PrimaryTile({
  icon,
  label,
  value,
  hint,
  tone = "default",
}: PrimaryTileProps) {
  return (
    <div className="rounded-xl border border-(--color-border) bg-(--color-surface) p-4">
      <div className="flex items-start justify-between">
        <span className="text-xs font-medium uppercase tracking-wide text-(--color-muted-foreground)">
          {label}
        </span>
        <span className="text-(--color-muted-foreground)">{icon}</span>
      </div>
      <div
        className={cn(
          "mt-2 text-2xl font-semibold tracking-tight",
          PRIMARY_TONE[tone],
        )}
      >
        {value}
      </div>
      {hint && (
        <p className="mt-1 text-[11px] text-(--color-muted-foreground)">
          {hint}
        </p>
      )}
    </div>
  );
}

interface SecondaryTileProps {
  icon: React.ReactNode;
  label: string;
  value: string;
  hint?: string;
  tone?: "default" | "warning" | "success";
}

function SecondaryTile({
  icon,
  label,
  value,
  hint,
  tone = "default",
}: SecondaryTileProps) {
  const toneClass =
    tone === "warning"
      ? "text-amber-600"
      : tone === "success"
        ? "text-emerald-600"
        : "text-(--color-foreground)";
  return (
    <div className="rounded-lg border border-(--color-border)/60 bg-(--color-surface-2)/40 p-3">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-medium uppercase tracking-wide text-(--color-muted-foreground)">
          {label}
        </span>
        <span className="text-(--color-muted-foreground)">{icon}</span>
      </div>
      <div className={cn("mt-1.5 text-lg font-semibold", toneClass)}>
        {value}
      </div>
      {hint && (
        <p className="mt-0.5 text-[10px] leading-snug text-(--color-muted-foreground)">
          {hint}
        </p>
      )}
    </div>
  );
}

interface BreakdownRowInput {
  referenceRevenue: number;
  khauTru: number;
  thueGTGT: number;
  thueTNCN: number;
  marketing: number;
  earnings: number;
}

/**
 * Build the 5 rows the chart renders. Costs first, take-home last.
 * Each row gets its own colour tone so the bar fill matches the
 * semantic ("chi phí" → amber, "thực nhận" → emerald, "chưa rõ" →
 * muted). The chart is pure presentation — it never recomputes pct.
 */
function buildBreakdownRows(input: BreakdownRowInput): BreakdownRow[] {
  const { referenceRevenue } = input;
  return [
    {
      label: "Chiết khấu nền tảng",
      amount: input.khauTru,
      pct: pctOf(input.khauTru, referenceRevenue),
      tone: "warning",
    },
    {
      label: "VAT",
      amount: input.thueGTGT,
      pct: pctOf(input.thueGTGT, referenceRevenue),
      tone: "warning",
    },
    {
      label: "Marketing",
      amount: input.marketing,
      pct: pctOf(input.marketing, referenceRevenue),
      tone: "muted",
    },
    {
      label: "Thuế TNCN (PIT)",
      amount: input.thueTNCN,
      pct: pctOf(input.thueTNCN, referenceRevenue),
      tone: "warning",
    },
    {
      label: "Số tiền thực nhận",
      amount: input.earnings,
      pct: pctOf(input.earnings, referenceRevenue),
      tone: "success",
    },
  ];
}

function SkeletonGrid() {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-24 w-full" />
        ))}
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-16 w-full" />
        ))}
      </div>
      <Skeleton className="h-48 w-full" />
    </div>
  );
}

function ErrorBanner() {
  return (
    <div className="flex items-start gap-3 rounded-lg border border-amber-500/40 bg-amber-500/5 p-4 text-sm">
      <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" />
      <div>
        <p className="font-medium text-amber-700">
          Không thể tải báo cáo tài chính
        </p>
        <p className="mt-1 text-amber-700/80">
          Grab từ chối yêu cầu hoặc mất kết nối. Vui lòng thử lại sau ít phút,
          hoặc kiểm tra phiên đăng nhập Grab tại trang Cài đặt.
        </p>
      </div>
    </div>
  );
}

// CalendarRange + TrendingUp are intentionally imported above for
// future use (date-range display + delta arrows). Mark them used so
// the import isn't flagged while keeping the door open for follow-ups.
void CalendarRange;
void TrendingUp;