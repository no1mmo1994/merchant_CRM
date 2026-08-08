"use client";

import * as React from "react";
import { AlertTriangle, Award, Check, RefreshCw, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useGoldenApron,
  type TierLevel,
  type TierMetric,
} from "@/lib/api/golden-apron";
import { useStores } from "@/lib/api/stores";
import { useUIStore } from "@/lib/stores/ui-store";
import { cn } from "@/lib/utils";

/**
 * Tạp Dề Vàng — which tier the store is on and what each one demands.
 *
 * The question the page answers is "what is stopping me moving up", so
 * unmet conditions lead: the next tier the store hasn't fully met is
 * expanded first, and within every tier the failing metrics sort to the
 * top. A list in Grab's own order buries the three things that matter
 * under the six that are already fine.
 */

/** Tier tints, warmest at the top of the ladder. */
const TIER_TONE: Record<string, { ring: string; text: string; bg: string }> = {
  "Cơ Bản": {
    ring: "border-(--color-border)",
    text: "text-(--color-muted-foreground)",
    bg: "bg-(--color-surface-3)",
  },
  Bạc: {
    ring: "border-slate-400/40",
    text: "text-slate-400",
    bg: "bg-slate-400/10",
  },
  Vàng: {
    ring: "border-amber-400/50",
    text: "text-amber-500",
    bg: "bg-amber-400/10",
  },
};

function tone(name: string) {
  return TIER_TONE[name] ?? TIER_TONE["Cơ Bản"];
}

function formatNumber(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(2);
}

/**
 * How far along a metric is, 0–1, or null when it can't be known.
 *
 * A `min` metric fills as it climbs. A `max` metric is a budget being
 * spent: at the limit the bar is full, which is the point at which the
 * tier is lost — so "full" means trouble on those, and the colour says
 * so rather than the length.
 */
function progressOf(metric: TierMetric): number | null {
  const { value, direction } = metric.threshold;
  if (metric.current === null || value === null || value <= 0) return null;
  const ratio = metric.current / value;
  return Math.max(0, Math.min(1, direction === "max" ? ratio : ratio));
}

function MetricRow({ metric }: { metric: TierMetric }) {
  const progress = progressOf(metric);
  const isMax = metric.threshold.direction === "max";
  const unit = metric.threshold.is_percent ? "%" : "";

  return (
    <div className="border-t border-(--color-border) py-2.5 first:border-t-0">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5">
            {metric.achieved ? (
              <Check className="h-3.5 w-3.5 shrink-0 text-emerald-500" />
            ) : (
              <X className="h-3.5 w-3.5 shrink-0 text-red-500" />
            )}
            <span className="text-sm text-(--color-foreground)">
              {metric.label || metric.metric}
            </span>
          </div>
          {/* Grab's own sentence stays visible — the parsed threshold below
              is a convenience, not the record. */}
          <div className="mt-0.5 pl-5 text-xs text-(--color-muted-foreground)">
            {metric.requirement || "—"}
          </div>
        </div>
        <div className="shrink-0 text-right">
          <div
            className={cn(
              "text-sm font-semibold",
              metric.current === null
                ? "italic text-(--color-muted-foreground)"
                : "font-mono " +
                  (metric.achieved ? "text-emerald-600" : "text-red-500"),
            )}
            title={
              metric.current === null
                ? "Grab không trả về số liệu cho chỉ số này"
                : undefined
            }
          >
            {/* Never 0 for "unknown": on "Thiếu món hoặc sai món" a zero
                would read as a spotless record. Set in the body font, not
                mono — a lowercase phrase in a monospaced numeric column
                is what made this hard to read. */}
            {metric.current === null
              ? "Chưa rõ"
              : `${formatNumber(metric.current)}${unit}`}
          </div>
          {metric.threshold.value !== null && (
            <div className="text-[11px] text-(--color-muted-foreground)">
              {isMax ? "tối đa" : "cần"} {formatNumber(metric.threshold.value)}
              {unit}
            </div>
          )}
        </div>
      </div>

      {progress !== null && (
        <div className="mt-1.5 ml-5 h-1 overflow-hidden rounded-full bg-(--color-surface-3)">
          <div
            className={cn(
              "h-full rounded-full transition-all",
              metric.achieved ? "bg-emerald-500" : "bg-red-500",
            )}
            style={{ width: `${Math.round(progress * 100)}%` }}
          />
        </div>
      )}
    </div>
  );
}

function TierCard({
  level,
  defaultOpen,
}: {
  level: TierLevel;
  defaultOpen: boolean;
}) {
  const [open, setOpen] = React.useState(defaultOpen);
  const t = tone(level.name);
  const missing = level.totalCount - level.achievedCount;

  // Unmet first — those are the actions. Grab's own order puts the six
  // already-satisfied conditions above the three that block the tier.
  const sorted = React.useMemo(
    () =>
      [...level.metrics].sort(
        (a, b) => Number(a.achieved) - Number(b.achieved),
      ),
    [level.metrics],
  );

  return (
    <Card className={cn("border", t.ring)}>
      <CardContent className="p-0">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex w-full items-center gap-3 p-4 text-left"
        >
          <div className={cn("rounded-full p-2", t.bg)}>
            <Award className={cn("h-5 w-5", t.text)} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold text-(--color-foreground)">
                {level.name}
              </span>
              {level.isCurrent && (
                <Badge variant="secondary" className="bg-emerald-500/10 text-emerald-600">
                  Hạng hiện tại
                </Badge>
              )}
              {missing === 0 && !level.isCurrent && (
                <Badge variant="secondary" className="bg-emerald-500/10 text-emerald-600">
                  Đủ điều kiện
                </Badge>
              )}
            </div>
            <div className="mt-0.5 text-xs text-(--color-muted-foreground)">
              {missing === 0
                ? `Đạt cả ${level.totalCount} điều kiện`
                : `Còn thiếu ${missing}/${level.totalCount} điều kiện`}
            </div>
          </div>
          <div className="shrink-0 text-right">
            <div className="font-mono text-lg font-semibold text-(--color-foreground)">
              {level.achievedCount}/{level.totalCount}
            </div>
            <div className="text-[11px] text-(--color-muted-foreground)">
              {open ? "Thu gọn" : "Xem chi tiết"}
            </div>
          </div>
        </button>

        {open && (
          <div className="border-t border-(--color-border) px-4 pb-3">
            {sorted.map((m) => (
              <MetricRow key={`${level.name}-${m.metric}`} metric={m} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function GoldenApronClient() {
  // Store-keyed so switching branches doesn't leave the previous store's
  // ladder on screen — the endpoint follows the active-store cookie.
  const activeStoreId = useUIStore((s) => s.activeStoreId);
  const { data: stores } = useStores();
  const activeStore =
    (stores ?? []).find((s) => String(s.id) === activeStoreId) ?? (stores ?? [])[0];
  const { data, isLoading, error, refetch, isRefetching } = useGoldenApron(
    activeStore?.merchant_id ?? null,
  );

  const levels = data?.levels ?? [];
  // The first rung not fully met is what the operator is working towards.
  const nextIndex = levels.findIndex(
    (l) => l.achievedCount < l.totalCount,
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-sm text-(--color-muted-foreground)">
          Hạng do Grab chấm theo tháng. Số liệu dưới đây tính từ{" "}
          {data?.periodStart || "đầu tháng"} đến {data?.periodEnd || "hôm nay"}.
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => void refetch()}
          disabled={isRefetching}
        >
          <RefreshCw className={cn("mr-1 h-3.5 w-3.5", isRefetching && "animate-spin")} />
          Làm mới
        </Button>
      </div>

      {(data?.warnings.length ?? 0) > 0 && (
        <div className="flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-xs text-amber-700 dark:text-amber-200">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <div className="space-y-1">
            {data?.warnings.map((w, i) => (
              <p key={i}>{w}</p>
            ))}
          </div>
        </div>
      )}

      {error ? (
        <Card className="border-(--color-border)">
          <CardContent className="p-6 text-center text-sm text-(--color-muted-foreground)">
            {error instanceof Error
              ? error.message
              : "Không tải được thông tin Tạp Dề Vàng."}
          </CardContent>
        </Card>
      ) : isLoading ? (
        <div className="space-y-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-24 w-full rounded-xl" />
          ))}
        </div>
      ) : levels.length === 0 ? (
        <Card className="border-(--color-border)">
          <CardContent className="p-6 text-center text-sm text-(--color-muted-foreground)">
            Grab chưa trả về thông tin hạng cho cửa hàng này.
          </CardContent>
        </Card>
      ) : (
        <>
          <Card className="border-(--color-border)">
            <CardContent className="flex flex-wrap items-center gap-4 p-4">
              <div className="flex items-center gap-3">
                <div className={cn("rounded-full p-2.5", tone(data!.currentTier).bg)}>
                  <Award className={cn("h-6 w-6", tone(data!.currentTier).text)} />
                </div>
                <div>
                  <div className="text-xs text-(--color-muted-foreground)">
                    Hạng hiện tại
                  </div>
                  <div className="text-lg font-semibold text-(--color-foreground)">
                    {data!.currentTier || "Chưa rõ"}
                  </div>
                </div>
              </div>

              {data!.isFirstMonth && (
                <Badge variant="outline">
                  Tháng đầu tham gia — Grab áp dụng điều kiện riêng
                </Badge>
              )}

              <div className="ml-auto flex gap-5 text-right">
                <div>
                  <div className="text-xs text-(--color-muted-foreground)">
                    Số sao
                  </div>
                  <div className="font-mono text-lg font-semibold text-(--color-foreground)">
                    {data!.rating === null ? "—" : data!.rating.toFixed(1)}
                  </div>
                </div>
                <div>
                  <div className="text-xs text-(--color-muted-foreground)">
                    Lượt đánh giá
                  </div>
                  <div className="font-mono text-lg font-semibold text-(--color-foreground)">
                    {data!.ratingCount ?? "—"}
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>

          <div className="space-y-3">
            {levels.map((level, i) => (
              <TierCard
                key={level.name}
                level={level}
                // Open the rung being worked towards; the rest fold away.
                defaultOpen={i === nextIndex}
              />
            ))}
          </div>

          <p className="text-[11px] text-(--color-muted-foreground)">
            Điều kiện và trạng thái đạt/chưa đạt lấy nguyên từ Grab. Số sao và
            lượt đánh giá tính trên toàn bộ lịch sử, các chỉ số còn lại tính
            trong tháng này.
          </p>
        </>
      )}
    </div>
  );
}
