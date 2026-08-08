"use client";

import * as React from "react";
import {
  AlertTriangle,
  Banknote,
  CalendarRange,
  Coins,
  DollarSign,
  Megaphone,
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
            {/* Grab's own label for the row. A group can hold several
                unrelated costs — the platform commission and the ad fee
                both land in "Khấu trừ" — and "#1 / #2" told the operator
                nothing about which was which. */}
            <span className="truncate pr-2 text-[11px]">
              {v.name && v.name !== group.label ? v.name : `#${idx + 1}`}
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
  // "Khấu trừ" is a bucket, not a single number: the platform commission
  // and the advertising fee are separate rows in it. The card read only
  // the first, so a store paying for ads saw a deduction total short by
  // exactly the ad spend.
  const sumValue = (
    label: string,
  ): FinancialMetricGroup["values"][number] | null => {
    const values = metricsByLabel.get(label)?.values ?? [];
    if (values.length === 0) return null;
    if (values.length === 1) return values[0];
    return {
      display: "",
      value_minor: values.reduce((acc, v) => acc + v.value_minor, 0),
    };
  };

  // How many separate costs that bucket holds, so the hint can say so
  // rather than presenting a sum as though it were a single fee.
  const deductionRows = metricsByLabel.get("Khấu trừ")?.values.length ?? 0;

  /**
   * What the store spent on Grab advertising.
   *
   * There is no dedicated field for it. Grab files the ad spend as one
   * row inside the deduction bucket — the backend keeps each row's own
   * label, so it arrives as a "Khấu trừ" value named "Phí quảng cáo".
   * Depending on how Grab nests the accordion it can also surface as a
   * group of its own, so both are searched.
   *
   * Summed rather than first-match: a period can carry more than one
   * marketing line (campaign fee and net marketing fee, for instance).
   */
  const marketingValue = (): FinancialMetricGroup["values"][number] | null => {
    const isMarketing = (s: string) => {
      const t = s.toLowerCase();
      return (
        t.includes("quảng cáo") ||
        t.includes("tiếp thị") ||
        t.includes("marketing") ||
        t.includes("advertis")
      );
    };
    let total = 0;
    let found = false;
    for (const group of metrics) {
      const groupIsMarketing = isMarketing(group.label);
      for (const v of group.values) {
        if (groupIsMarketing || isMarketing(v.name ?? "")) {
          total += v.value_minor;
          found = true;
        }
      }
    }
    return found ? { display: "", value_minor: total } : null;
  };
  const marketing = marketingValue();

  return (
    <div className="space-y-6">
      {/* Row 1 — the money story, in the order the merchant thinks about
          it: what came in, what is left after Grab's cut, what actually
          lands in the bank. "Thu nhập ròng" was previously buried at the
          end of the fees row; it is the number the operator opens this
          page for, so it belongs here. */}
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
          hint={isLoading ? "Đang tải…" : "Sau khi trừ phí nền tảng và khấu trừ khác."}
        />
        {/* Was "Thu nhập ròng", which Grab never returns for this store —
            the card read "— đ" on every report. Marketing spend is the
            one deduction the merchant actually controls, and it was
            invisible: buried as an unnamed second row inside Khấu trừ.
            Labelled as already-counted so nobody adds it to Khấu trừ
            again. */}
        <MetricCard
          icon={<Megaphone className="h-4 w-4" />}
          label="Chi phí tiếp thị"
          value={isLoading ? "—" : marketing ? formatBalance(marketing) : "—"}
          tone="warning"
          hint={
            isLoading
              ? "Đang tải…"
              : marketing
                ? "Phí quảng cáo Grab — đã nằm trong Khấu trừ."
                : "Kỳ này không có chi phí quảng cáo."
          }
        />
      </div>

      {/* Row 2 — what was taken off. Khấu trừ sums its rows: it holds the
          platform commission AND the advertising fee. */}
      <div className="grid gap-4 md:grid-cols-3">
        <MetricCard
          icon={<Banknote className="h-4 w-4" />}
          label="Khấu trừ"
          value={isLoading ? "—" : formatBalance(sumValue("Khấu trừ"))}
          tone="warning"
          hint={
            isLoading
              ? "Đang tải…"
              : deductionRows > 1
                ? `Phí nền tảng + quảng cáo + chiết khấu (${deductionRows} khoản).`
                : "Phí nền tảng + chiết khấu."
          }
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
      </div>

      {/* Row 3 — the two balances Grab holds. They used to be a KPI card
          and a near-empty half-width card; both are single numbers the
          operator only glances at, so they share one compact strip. */}
      <Card className="border-(--color-border)">
        <CardContent className="grid gap-4 p-4 sm:grid-cols-2">
          {[
            {
              title: "Số dư doanh thu",
              value: data?.sales_balance,
              hint: "Số dư doanh thu hiện có trên Grab.",
              accent: "text-(--color-foreground)",
            },
            {
              title: "Số dư thu nhập",
              value: data?.earnings_balance,
              hint: "Số dư khả dụng để yêu cầu rút tiền.",
              accent: "text-emerald-600",
            },
          ].map((b) => (
            <div key={b.title} className="flex items-center gap-3">
              <Wallet className="h-4 w-4 shrink-0 text-(--color-muted-foreground)" />
              <div className="min-w-0">
                <div className="text-xs text-(--color-muted-foreground)">
                  {b.title}
                </div>
                {isLoading ? (
                  <Skeleton className="mt-1 h-6 w-32" />
                ) : (
                  <div className={`text-xl font-bold ${b.accent}`}>
                    {formatBalance(b.value)}
                  </div>
                )}
                <p className="text-[11px] text-(--color-muted-foreground)">
                  {b.hint}
                </p>
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

      {/* Row 4 — full width. It lists every label Grab returned, several
          of them with multiple rows; at half width the numbers wrapped. */}
      <div className="grid gap-4">
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
