"use client";

import * as React from "react";
import { AlertTriangle, HandCoins, RefreshCw, TrendingUp } from "lucide-react";

import { ProgramDetailDialog } from "@/components/marketing/ProgramDetailDialog";
import { ProgramImage } from "@/components/marketing/ProgramImage";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useMarketing,
  type CampaignStatus,
  type MarketingCampaign,
  type SpotlightEvent,
} from "@/lib/api/marketing";
import { cn } from "@/lib/utils";

/** Grab's buckets, in the Merchant app's order and wording. */
const STATUS_SECTIONS: ReadonlyArray<{ key: CampaignStatus; label: string }> = [
  { key: "evergreen", label: "Chiến dịch luôn hoạt động" },
  { key: "ongoing", label: "Đang hoạt động" },
  { key: "upcoming", label: "Sắp diễn ra" },
  { key: "inReview", label: "Đang xét duyệt" },
  { key: "paused", label: "Tạm dừng" },
  { key: "past", label: "Đã hoàn tất" },
];

function formatVnd(value: number): string {
  return `${Math.round(value).toLocaleString("vi-VN")}đ`;
}

/**
 * "Kết thúc sau 5 ngày" / "Bắt đầu vào ngày 07 Jul", matching the app.
 *
 * A campaign that ends soon is the one the operator has to act on, so
 * the remaining days lead. Anything further out just shows the date.
 */
function scheduleLabel(c: MarketingCampaign): { text: string; urgent: boolean } {
  const now = Date.now();
  const end = c.end_time ? Date.parse(c.end_time) : NaN;
  const start = c.start_time ? Date.parse(c.start_time) : NaN;

  if (Number.isFinite(end) && end > now) {
    const days = Math.ceil((end - now) / 86_400_000);
    if (days <= 7) {
      return { text: `Kết thúc sau ${days} ngày`, urgent: true };
    }
  }
  if (Number.isFinite(start)) {
    const d = new Date(start);
    const month = d.toLocaleString("en-US", { month: "short" });
    return {
      text: `Bắt đầu vào ngày ${String(d.getDate()).padStart(2, "0")} ${month}`,
      urgent: false,
    };
  }
  return { text: "", urgent: false };
}

/** Round thumbnail; falls back to an icon when the image is missing or dead. */
function Thumb({ src }: { src: string }) {
  return (
    <ProgramImage
      src={src}
      className="h-12 w-12 shrink-0 overflow-hidden rounded-full"
      iconClassName="h-5 w-5"
    />
  );
}

function CampaignRow({ campaign }: { campaign: MarketingCampaign }) {
  const sched = scheduleLabel(campaign);
  const perf = campaign.performance;

  return (
    <div className="flex items-center gap-3 border-b border-(--color-border) py-3 last:border-0">
      <Thumb src={campaign.image_url} />
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium text-(--color-foreground)">
          {campaign.name || "(Không tên)"}
        </div>
        <div className="mt-0.5 text-xs text-(--color-muted-foreground)">
          {campaign.campaign_type ? `${campaign.campaign_type} · ` : ""}
          <span className={cn(sched.urgent && "font-medium text-red-500")}>
            {sched.text}
          </span>
        </div>
        {perf.has_data && (
          <div className="mt-1 text-[11px] text-(--color-muted-foreground)">
            Đã chi {formatVnd(perf.marketing_spend)} · mang về{" "}
            {formatVnd(perf.assisted_sales)} ({perf.assisted_orders} đơn)
          </div>
        )}
      </div>
      {/* ROMS = doanh thu mang về / tiền đã chi. Chỉ hiện khi có số thật —
          một chiến dịch chưa chạy mà hiện "0.0x" trông như đang lỗ. */}
      {perf.has_data && perf.roms > 0 && (
        <Badge
          variant="secondary"
          className="shrink-0 gap-1 bg-emerald-500/10 font-mono text-emerald-600"
          title="ROMS — doanh thu mang về trên mỗi đồng chi cho quảng cáo"
        >
          <TrendingUp className="h-3 w-3" />
          {perf.roms.toFixed(1)}x
        </Badge>
      )}
    </div>
  );
}

function EventCard({
  event,
  onOpen,
}: {
  event: SpotlightEvent;
  onOpen: () => void;
}) {
  return (
    // A button, not a div with onClick: the terms behind this card are what
    // decide whether the store loses money, so it has to be reachable by
    // keyboard and announced as actionable.
    <button
      type="button"
      onClick={onOpen}
      className="flex w-full gap-3 rounded-xl border border-(--color-border) bg-(--color-surface-2) p-3 text-left transition-colors hover:border-(--color-brand)/50 hover:bg-(--color-surface-3)/40"
    >
      <ProgramImage
        src={event.image_url}
        className="h-20 w-20 shrink-0 overflow-hidden rounded-lg"
        iconClassName="h-6 w-6"
      />
      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-2">
          <div className="text-sm font-medium text-(--color-foreground)">
            {event.name || "(Không tên)"}
          </div>
          <div className="flex shrink-0 flex-wrap justify-end gap-1">
            <Badge
              variant={event.is_eligible ? "secondary" : "outline"}
              className={cn(
                event.is_eligible && "bg-emerald-500/10 text-emerald-600",
              )}
            >
              {event.is_eligible ? "Đủ điều kiện" : "Chưa đủ ĐK"}
            </Badge>
            {/* The one fact that decides whether a program is worth
                opening, and the list endpoint doesn't carry it — the
                backend fetches it per program so it's visible here rather
                than one dialog at a time. `null` means the lookup didn't
                land; no badge beats a guessed one. */}
            {event.is_grab_cofund === true && (
              <Badge
                variant="secondary"
                className="gap-1 bg-emerald-500/10 text-emerald-600"
                // The share stays in the tooltip rather than the label.
                // On the card it was the *best* of several tiers, so a
                // program funded at 20% and 8.3% read as a flat 20% and
                // disagreed with its own detail view. The per-tier figures
                // in the dialog are where that number belongs.
                title={
                  event.max_grab_funded_pct !== null
                    ? `Grab chịu tới ${(event.max_grab_funded_pct * 100).toFixed(1)}% mức giảm — mở chi tiết để xem từng bậc`
                    : "Grab chịu một phần mức giảm giá"
                }
              >
                <HandCoins className="h-3 w-3" />
                Grab đồng tài trợ
              </Badge>
            )}
            {event.is_grab_cofund === false && (
              <Badge variant="outline" className="text-red-500">
                Shop chịu 100%
              </Badge>
            )}
          </div>
        </div>
        <p className="mt-1 line-clamp-2 text-xs text-(--color-muted-foreground)">
          {event.description}
        </p>
        <span className="mt-1.5 inline-block text-[11px] font-medium text-(--color-brand)">
          Xem điều khoản &amp; mức Grab tài trợ →
        </span>
      </div>
    </button>
  );
}

export function MarketingClient() {
  const { data, isLoading, error, refetch, isRefetching } = useMarketing();
  const [tab, setTab] = React.useState<"available" | "joined">("available");
  // Which program's terms to show, and whether the dialog is open —
  // two pieces of state, not one. The dialog animates out over ~100ms
  // while still mounted, so clearing the event on close would blank its
  // title mid-animation. Keeping it also makes reopening the same
  // program instant off the React Query cache.
  //
  // One program at a time: each costs its own Grab round-trip, so
  // nothing is fetched until a card is clicked.
  const [detailEvent, setDetailEvent] = React.useState<SpotlightEvent | null>(null);
  const [detailOpen, setDetailOpen] = React.useState(false);

  const campaigns = data?.campaigns ?? [];
  const events = data?.events ?? [];
  const counts = data?.counts;

  const byStatus = React.useMemo(() => {
    const m = new Map<string, MarketingCampaign[]>();
    for (const c of campaigns) {
      const list = m.get(c.status) ?? [];
      list.push(c);
      m.set(c.status, list);
    }
    return m;
  }, [campaigns]);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <div className="flex gap-1 rounded-lg border border-(--color-border) p-1">
          {(
            [
              ["available", `Chương trình hiện có${events.length ? ` (${events.length})` : ""}`],
              ["joined", `Đang tham gia${counts?.total ? ` (${counts.total})` : ""}`],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setTab(key)}
              className={cn(
                "rounded-md px-3 py-1.5 text-sm transition-colors",
                tab === key
                  ? "bg-(--color-brand) text-white"
                  : "text-(--color-muted-foreground) hover:bg-(--color-surface-3)/40",
              )}
            >
              {label}
            </button>
          ))}
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => void refetch()}
          disabled={isRefetching}
          className="ml-auto"
        >
          <RefreshCw className={cn("mr-1 h-3.5 w-3.5", isRefetching && "animate-spin")} />
          Làm mới
        </Button>
      </div>

      {/* Each half can fail on its own, so warnings sit above both tabs
          rather than replacing the content — the surviving half still
          renders underneath. */}
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
            {error instanceof Error ? error.message : "Không tải được dữ liệu tiếp thị."}
          </CardContent>
        </Card>
      ) : isLoading ? (
        <div className="space-y-2">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-24 w-full rounded-xl" />
          ))}
        </div>
      ) : tab === "available" ? (
        events.length === 0 ? (
          <Card className="border-(--color-border)">
            <CardContent className="p-6 text-center text-sm text-(--color-muted-foreground)">
              Hiện không có chương trình nào được mời.
            </CardContent>
          </Card>
        ) : (
          <div className="grid gap-3 md:grid-cols-2">
            {events.map((e) => (
              <EventCard
                key={e.event_id || e.name}
                event={e}
                onOpen={() => {
                  setDetailEvent(e);
                  setDetailOpen(true);
                }}
              />
            ))}
          </div>
        )
      ) : campaigns.length === 0 ? (
        <Card className="border-(--color-border)">
          <CardContent className="p-6 text-center text-sm text-(--color-muted-foreground)">
            Chưa tham gia chiến dịch nào.
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {STATUS_SECTIONS.map(({ key, label }) => {
            const list = byStatus.get(key) ?? [];
            if (list.length === 0) return null;
            return (
              <Card key={key} className="border-(--color-border)">
                <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-1">
                  <CardTitle className="text-sm font-medium">{label}</CardTitle>
                  <Badge variant="secondary">{list.length}</Badge>
                </CardHeader>
                <CardContent className="pt-0">
                  {list.map((c) => (
                    <CampaignRow key={c.campaign_id || c.name} campaign={c} />
                  ))}
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}

      <ProgramDetailDialog
        open={detailOpen}
        eventId={detailEvent?.event_id ?? null}
        eventName={detailEvent?.name ?? ""}
        onClose={() => setDetailOpen(false)}
      />
    </div>
  );
}
