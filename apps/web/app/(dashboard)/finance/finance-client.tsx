"use client";

import * as React from "react";
import {
  AlertTriangle,
  Banknote,
  CalendarRange,
  Coins,
  DollarSign,
  Receipt,
  RefreshCw,
  Wallet,
} from "lucide-react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useFinanceSummary,
  useFinanceTransactions,
  useFinanceSettlements,
  type FinancialMetricGroup,
  type FinancialSummaryResponse,
  type FinancialTransaction,
  type FinancialSettlement,
} from "@/lib/api/finance";
import { ApiError } from "@/lib/api";
import { DateRangePicker, defaultDateRange } from "@/components/dashboard/DateRangePicker";
import { toast } from "sonner";

/** Format a VND amount in `12.000 ₫` style matching the Grab Merchant UI. */
function formatVnd(value: number): string {
  if (!Number.isFinite(value) || value === 0) return "0 ₫";
  return `${value.toLocaleString("vi-VN")} ₫`;
}

/** Display string from backend, or `value_minor` formatted as fallback. */
function formatBalance(balance: { display: string; value_minor: number } | null | undefined): string {
  if (!balance) return "— ₫";
  if (balance.display && balance.display.trim().length > 0) return balance.display;
  return formatVnd(balance.value_minor);
}

/**
 * Parse Grab's ISO ``datetime`` (e.g. ``"2026-07-31T21:56:00Z"``).
 *
 * Returns ``null`` when the string is empty / unparseable so callers
 * can fall back to the pre-formatted Grab strings (``display_date`` /
 * ``transaction_date``) — those are populated by Grab even when ISO
 * parsing fails.
 */
function parseGrabIso(iso: string | undefined | null): Date | null {
  if (!iso) return null;
  // Reject obviously-bad input without paying the Date constructor cost.
  if (iso.length < 10) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d;
}

/**
 * Compose the prominent "Chi tiết thanh toán" date label for a row.
 *
 * Grab sends two pre-formatted strings per row:
 *   - ``display_date``     → ``"31 07 2026"``         (date-only)
 *   - ``transaction_date`` → ``"01/08/2026 04:56AM"`` (local datetime)
 *   - ``datetime``         → ISO UTC timestamp        (always present per Grab)
 *
 * In practice Grab sometimes leaves the pre-formatted strings empty
 * (we've seen this on accounts where the backend only fills ISO).
 * The dashboard MUST still render a date, so we fall back to deriving
 * both labels from ``datetime`` — that gives us a stable source that
 * works regardless of what Grab's serializer does.
 *
 * The derived time uses UTC getters (``getUTCHours`` etc.) so it
 * matches the wall-clock format Grab sends (``"04:55AM"``) exactly
 * for events whose datetime is in UTC. When Grab's pre-formatted
 * strings are populated the user sees whatever timezone Grab's
 * server is in; when the fallback fires, the dashboard is honest
 * about being UTC-derived.
 *
 * Returns ``{ display: "", transaction: "" }`` when ALL three sources
 * are empty/unparseable so the row renders an em-dash placeholder
 * via the ``|| "—"`` fallback at the call site (not ``"undefined"``).
 */
function deriveSettlementDates(row: FinancialSettlement): {
  display: string;
  transaction: string;
} {
  const grabDisplay = row.display_date?.trim() ?? "";
  const grabTx = row.transaction_date?.trim() ?? "";
  const iso = parseGrabIso(row.datetime);

  if (grabDisplay && grabTx) {
    return { display: grabDisplay, transaction: grabTx };
  }

  if (!iso) {
    return { display: grabDisplay, transaction: grabTx };
  }

  const derivedDisplay =
    grabDisplay ||
    `${String(iso.getUTCDate()).padStart(2, "0")} ${String(iso.getUTCMonth() + 1).padStart(2, "0")} ${iso.getUTCFullYear()}`;

  const hours24 = iso.getUTCHours();
  const minutes = String(iso.getUTCMinutes()).padStart(2, "0");
  const ampm = hours24 >= 12 ? "PM" : "AM";
  const hours12 = hours24 % 12 === 0 ? 12 : hours24 % 12;
  const derivedTx =
    grabTx ||
    `${String(iso.getUTCDate()).padStart(2, "0")}/${String(iso.getUTCMonth() + 1).padStart(2, "0")}/${iso.getUTCFullYear()} ${hours12}:${minutes}${ampm}`;

  return { display: derivedDisplay, transaction: derivedTx };
}

interface MetricCardProps {
  icon: React.ReactNode;
  label: string;
  value: string;
  hint?: string;
  tone?: "brand" | "default" | "warning" | "success";
}

const TONE_VALUE: Record<NonNullable<MetricCardProps["tone"]>, string> = {
  brand: "text-(--color-brand)",
  default: "text-(--color-foreground)",
  warning: "text-amber-700",
  success: "text-emerald-700",
};

/**
 * One KPI card.  Layout matches the rest of the dashboard (icon top-right,
 * value as the headline, hint as a small footer line). `tone` tints the
 * value text so the operator can distinguish tax/deduction rows at a
 * glance.
 */
function MetricCard({ icon, label, value, hint, tone = "default" }: MetricCardProps) {
  return (
    <Card className="border-(--color-border)">
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium">{label}</CardTitle>
        <span className="text-(--color-muted-foreground)">{icon}</span>
      </CardHeader>
      <CardContent>
        <div className={`text-2xl font-bold ${TONE_VALUE[tone]}`}>{value}</div>
        {hint && (
          <p className="mt-1 text-xs text-(--color-muted-foreground)">{hint}</p>
        )}
      </CardContent>
    </Card>
  );
}

interface MetricGroupProps {
  group: FinancialMetricGroup;
}

/**
 * One Vietnamese-labelled metric and the (possibly multiple) values
 * Grab returned for it.  Same label can appear more than once
 * (`"Doanh thu"` once for gross, once for net) — keep the order stable
 * and show a thin separator between instances so the dashboard
 * preserves the CLI script's one-line-per-value output.
 */
function MetricGroupRow({ group }: MetricGroupProps) {
  return (
    <div className="flex flex-col gap-1 py-2 first:pt-0 last:pb-0">
      <div className="flex items-center justify-between gap-3">
        <div className="text-sm font-medium text-(--color-foreground)">
          {group.label}
        </div>
        <Badge variant="secondary" className="font-mono text-xs">
          {group.values.length} dòng
        </Badge>
      </div>
      <ul className="space-y-0.5 text-xs text-(--color-muted-foreground)">
        {group.values.map((v, idx) => (
          <li
            key={`${group.label}-${idx}`}
            className="flex items-center justify-between rounded bg-(--color-surface-2)/40 px-2 py-1"
          >
            <span className="text-[11px] uppercase tracking-wide">
              #{idx + 1}
            </span>
            <span className="font-mono text-(--color-foreground)">
              {v.display && v.display.trim().length > 0
                ? v.display
                : formatVnd(v.value_minor)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function FinanceClient() {
  const initial = React.useMemo(defaultDateRange, []);
  const [from, setFrom] = React.useState<string>(initial.from);
  const [to, setTo] = React.useState<string>(initial.to);
  const [appliedFrom, setAppliedFrom] = React.useState<string>(initial.from);
  const [appliedTo, setAppliedTo] = React.useState<string>(initial.to);
  const [tab, setTab] = React.useState<"summary" | "transactions" | "settlements">("summary");

  const query = useFinanceSummary(appliedFrom, appliedTo);
  const transactions = useFinanceTransactions(appliedFrom, appliedTo);
  const settlements = useFinanceSettlements(appliedFrom, appliedTo);

  const data: FinancialSummaryResponse | undefined = query.data;
  const isLoading = query.isLoading;
  const error = query.error;

  React.useEffect(() => {
    if (error instanceof ApiError) {
      toast.error(`Không thể tải báo cáo tài chính: ${error.message}`);
    }
  }, [error]);

  const applyRange = React.useCallback(() => {
    if (!from || !to) {
      toast.error("Vui lòng chọn cả ngày bắt đầu và ngày kết thúc.");
      return;
    }
    if (from > to) {
      toast.error("Ngày bắt đầu phải trước ngày kết thúc.");
      return;
    }
    setAppliedFrom(from);
    setAppliedTo(to);
  }, [from, to]);

  const refresh = React.useCallback(() => {
    if (from && to && from <= to) {
      setAppliedFrom(from);
      setAppliedTo(to);
    }
    void query.refetch();
    void transactions.refetch();
    void settlements.refetch();
  }, [from, to, query, transactions, settlements]);

  const metrics = data?.metrics ?? [];
  const warnings = data?.warnings ?? [];
  const metricsByLabel = React.useMemo(() => {
    const map = new Map<string, FinancialMetricGroup>();
    for (const m of metrics) map.set(m.label, m);
    return map;
  }, [metrics]);
  // Surface every discovered label — the UI is exhaustive so an
  // unlabeled Grab addition still shows up below.
  const orderedLabels = Array.from(metricsByLabel.keys());

  // Bug fix: every value in `metricsByLabel.get(label)?.values` is
  // already in display order from the backend (`_walk` walks Grab's
  // tree top-down, so `values[0]` is the canonical number for the
  // card). The previous `reduce` with seed `-1` returned null for
  // all-negative groups (`Khấu trừ`, `Thuế GTGT`, `Thuế TNCN`) because
  // every element failed `> -1`. Read the first slot instead.
  const firstValue = (label: string) =>
    metricsByLabel.get(label)?.values[0] ?? null;

  return (
    <div className="space-y-6 p-6">
      {/* Range picker — single form row, dates match the merchant
          script's `YYYY-MM-DD` input so the operator can copy a range
          they previously typed at the CLI. */}
      <Card className="border-(--color-border)">
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="flex items-center gap-2 text-sm font-medium">
            <CalendarRange className="h-4 w-4 text-(--color-muted-foreground)" />
            Khoảng thời gian
          </CardTitle>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={refresh}
            disabled={query.isFetching}
            className="gap-1.5"
            title="Tải lại"
          >
            <RefreshCw
              className={`h-3.5 w-3.5 ${query.isFetching ? "animate-spin" : ""}`}
            />
            Làm mới
          </Button>
        </CardHeader>
        <CardContent>
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
        </CardContent>
      </Card>

      {/* Tab switcher — mirrors the merchant mobile app: Tóm tắt /
          Giao dịch / Số tiền thu về. All three tabs share the same
          applied range above. */}
      <div
        role="tablist"
        aria-label="Báo cáo tài chính"
        className="flex gap-2 border-b border-(--color-border)"
      >
        <TabButton
          active={tab === "summary"}
          onClick={() => setTab("summary")}
        >
          Tóm tắt
        </TabButton>
        <TabButton
          active={tab === "transactions"}
          onClick={() => setTab("transactions")}
        >
          Giao dịch
        </TabButton>
        <TabButton
          active={tab === "settlements"}
          onClick={() => setTab("settlements")}
        >
          Số tiền thu về
        </TabButton>
      </div>

      {tab === "summary" && (
        <SummarySection
          data={data}
          isLoading={isLoading}
          warnings={warnings}
          metrics={metrics}
          orderedLabels={orderedLabels}
          metricsByLabel={metricsByLabel}
          firstValue={firstValue}
        />
      )}

      {tab === "transactions" && (
        <TransactionsSection query={transactions} />
      )}

      {tab === "settlements" && (
        <SettlementsSection query={settlements} />
      )}
    </div>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={[
        "-mb-px border-b-2 px-4 py-2 text-sm font-medium transition-colors",
        active
          ? "border-(--color-brand) text-(--color-foreground)"
          : "border-transparent text-(--color-muted-foreground) hover:text-(--color-foreground)",
      ].join(" ")}
    >
      {children}
    </button>
  );
}

// ─── "Tóm tắt" tab ───────────────────────────────────────────────────────────

function SummarySection({
  data,
  isLoading,
  warnings,
  metrics,
  orderedLabels,
  metricsByLabel,
  firstValue,
}: {
  data: FinancialSummaryResponse | undefined;
  isLoading: boolean;
  warnings: string[];
  metrics: FinancialMetricGroup[];
  orderedLabels: string[];
  metricsByLabel: Map<string, FinancialMetricGroup>;
  firstValue: (label: string) => FinancialMetricGroup["values"][number] | null;
}) {
  return (
    <div className="space-y-6">
      {/* Top KPI row — uses the canonical 3-col grid pattern from the
          placeholder, but now backed by real numbers.  Order mirrors
          the merchant's mental model: gross → net → deduction. */}
      <div className="grid gap-4 md:grid-cols-3">
        <MetricCard
          icon={<DollarSign className="h-4 w-4" />}
          label="Doanh thu (gross)"
          value={isLoading ? "—" : formatBalance(firstValue("Doanh thu"))}
          hint={isLoading ? "Đang tải…" : "Tổng doanh thu trước khi trừ phí và thuế."}
          tone="brand"
        />
        <MetricCard
          icon={<Receipt className="h-4 w-4" />}
          label="Doanh thu ròng"
          value={isLoading ? "—" : formatBalance(firstValue("Doanh thu ròng"))}
          hint={isLoading ? "Đang tải…" : "Doanh thu sau khi trừ phí nền tảng và khấu trừ khác."}
        />
        <MetricCard
          icon={<Wallet className="h-4 w-4" />}
          label="Số dư doanh thu (Sales Balance)"
          value={isLoading ? "—" : formatBalance(data?.sales_balance)}
          hint={isLoading ? "Đang tải…" : "Số dư doanh thu hiện có trên Grab."}
        />
      </div>

      {/* Second KPI row — deductions + taxes + take-home.  Kept as its
          own row so the operator can see the tax breakdown without
          scrolling past the gross/net numbers. */}
      <div className="grid gap-4 md:grid-cols-4">
        <MetricCard
          icon={<Banknote className="h-4 w-4" />}
          label="Khấu trừ"
          value={isLoading ? "—" : formatBalance(firstValue("Khấu trừ"))}
          tone="warning"
          hint={isLoading ? "Đang tải…" : "Phí nền tảng + chiết khấu."}
        />
        <MetricCard
          icon={<Banknote className="h-4 w-4" />}
          label="Thuế GTGT"
          value={isLoading ? "—" : formatBalance(firstValue("Thuế GTGT"))}
          tone="warning"
          hint={isLoading ? "Đang tải…" : "VAT trên doanh thu."}
        />
        <MetricCard
          icon={<Banknote className="h-4 w-4" />}
          label="Thuế TNCN"
          value={isLoading ? "—" : formatBalance(firstValue("Thuế TNCN"))}
          tone="warning"
          hint={isLoading ? "Đang tải…" : "Thuế thu nhập cá nhân."}
        />
        <MetricCard
          icon={<DollarSign className="h-4 w-4" />}
          label="Thu nhập ròng"
          value={isLoading ? "—" : formatBalance(firstValue("Thu nhập ròng"))}
          tone="success"
          hint={isLoading ? "Đang tải…" : "Số tiền cuối cùng merchant nhận."}
        />
      </div>

      {/* Earnings balance (separate card; merchant cares about this
          number independently of the gross / net numbers above). */}
      <div className="grid gap-4 md:grid-cols-2">
        <Card className="border-(--color-border)">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">
              Số dư thu nhập (Earnings Balance)
            </CardTitle>
            <Wallet className="h-4 w-4 text-(--color-muted-foreground)" />
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-8 w-40" />
            ) : (
              <div className="text-2xl font-bold text-emerald-700">
                {formatBalance(data?.earnings_balance)}
              </div>
            )}
            <p className="mt-1 text-xs text-(--color-muted-foreground)">
              Số dư khả dụng để yêu cầu rút tiền.
            </p>
          </CardContent>
        </Card>

        {/* Drill-down card — exhaustive list of every label Grab
            returned, not just the canonical six. */}
        <Card className="border-(--color-border)">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Chi tiết báo cáo</CardTitle>
            <Badge variant="secondary">{metrics.length}</Badge>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <div className="space-y-2">
                {[0, 1, 2, 3].map((i) => (
                  <Skeleton key={i} className="h-10 w-full" />
                ))}
              </div>
            ) : metrics.length === 0 ? (
              <div className="rounded-lg border border-dashed border-(--color-border) p-6 text-center text-sm text-(--color-muted-foreground)">
                {warnings[0] ??
                  "Chưa có dữ liệu chi tiết cho khoảng thời gian này."}
              </div>
            ) : (
              <div className="divide-y divide-(--color-border)">
                {orderedLabels.map((label) => {
                  const group = metricsByLabel.get(label)!;
                  return <MetricGroupRow key={label} group={group} />;
                })}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {warnings.length > 0 && metrics.length > 0 && (
        <div className="flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-50/50 p-3 text-xs text-amber-800">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <div className="space-y-1">
            {warnings.map((w, idx) => (
              <p key={idx}>{w}</p>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── "Giao dịch" tab ─────────────────────────────────────────────────────────

function TransactionsSection({
  query,
}: {
  query: ReturnType<typeof useFinanceTransactions>;
}) {
  if (query.isLoading) {
    return (
      <Card className="border-(--color-border)">
        <CardContent className="space-y-2 p-6">
          {[0, 1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </CardContent>
      </Card>
    );
  }
  if (query.isError) {
    return (
      <Card className="border-(--color-border)">
        <CardContent className="p-6 text-sm text-(--color-muted-foreground)">
          Không tải được lịch sử giao dịch. Vui lòng thử lại.
        </CardContent>
      </Card>
    );
  }

  const rows = query.data?.transactions ?? [];
  if (rows.length === 0) {
    return (
      <Card className="border-(--color-border)">
        <CardContent className="p-6 text-center text-sm text-(--color-muted-foreground)">
          Chưa có giao dịch nào trong khoảng thời gian này.
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="border-(--color-border)">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm font-medium">
          <Receipt className="h-4 w-4 text-(--color-muted-foreground)" />
          Giao dịch
          <Badge variant="secondary" className="ml-2">
            {rows.length}
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        <ul className="divide-y divide-(--color-border)">
          {rows.map((row) => (
            <TransactionRow key={row.id || row.datetime} row={row} />
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

function TransactionRow({ row }: { row: FinancialTransaction }) {
  const isNegative = row.amount < 0;
  return (
    <li className="grid grid-cols-12 items-center gap-3 px-4 py-3 text-sm">
      <div className="col-span-3 text-(--color-muted-foreground)">
        {row.display_date || row.transaction_date}
      </div>
      <div className="col-span-3 text-(--color-foreground)">
        {row.type_label || row.type || "—"}
      </div>
      <div className="col-span-4 truncate text-(--color-foreground)">
        {row.name || "—"}
      </div>
      <div
        className={[
          "col-span-2 text-right font-mono font-semibold",
          isNegative ? "text-amber-700" : "text-emerald-700",
        ].join(" ")}
      >
        {row.amount_display || formatVnd(row.amount)}
      </div>
    </li>
  );
}

// ─── "Số tiền thu về" tab ────────────────────────────────────────────────────

function SettlementsSection({
  query,
}: {
  query: ReturnType<typeof useFinanceSettlements>;
}) {
  if (query.isLoading) {
    return (
      <div className="space-y-4">
        <div className="grid gap-4 md:grid-cols-2">
          {[0, 1].map((i) => (
            <Skeleton key={i} className="h-24 w-full" />
          ))}
        </div>
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }
  if (query.isError) {
    return (
      <Card className="border-(--color-border)">
        <CardContent className="p-6 text-sm text-(--color-muted-foreground)">
          Không tải được lịch sử thanh toán. Vui lòng thử lại.
        </CardContent>
      </Card>
    );
  }

  const summary = query.data?.summary ?? null;
  const rows = query.data?.settlements ?? [];
  const payable = summary?.payable_to_merchant ?? 0;
  const owed = summary?.owed_to_grab ?? 0;

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-2">
        <MetricCard
          icon={<Wallet className="h-4 w-4" />}
          label="Số dư"
          value={formatVnd(payable)}
          tone="success"
          hint="Số tiền Grab còn nợ merchant."
        />
        <MetricCard
          icon={<Coins className="h-4 w-4" />}
          label="Còn thiếu Grab"
          value={formatVnd(owed)}
          tone="warning"
          hint="Số tiền merchant còn nợ Grab."
        />
      </div>

      <Card className="border-(--color-border)">
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-sm font-medium">
            <Banknote className="h-4 w-4 text-(--color-muted-foreground)" />
            Chi tiết thanh toán
            <Badge variant="secondary" className="ml-2">
              {rows.length}
            </Badge>
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {rows.length === 0 ? (
            <div className="p-6 text-center text-sm text-(--color-muted-foreground)">
              Chưa có thanh toán nào trong khoảng thời gian này.
            </div>
          ) : (
            <ul className="divide-y divide-(--color-border)">
              {rows.map((row) => (
                <SettlementRow key={row.id || row.datetime} row={row} />
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function SettlementRow({ row }: { row: FinancialSettlement }) {
  const { display, transaction } = deriveSettlementDates(row);
  return (
    <li className="grid grid-cols-12 items-center gap-3 px-4 py-3 text-sm">
      <div className="col-span-5 leading-tight">
        <div className="text-base font-medium text-(--color-foreground)">
          {display || "—"}
        </div>
        <div className="text-xs text-(--color-muted-foreground)">
          {transaction || "—"}
        </div>
      </div>
      <div className="col-span-4 text-right font-mono font-semibold text-emerald-700">
        {row.amount_display || formatVnd(row.amount)}
      </div>
      <div className="col-span-3 text-right">
        <span className="inline-flex items-center rounded-full bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700">
          {row.status_label || "Đã chuyển khoản"}
        </span>
      </div>
    </li>
  );
}
