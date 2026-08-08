"use client";

import * as React from "react";
import { AlertTriangle, Layers, Loader2 } from "lucide-react";

import { ProgramImage } from "@/components/marketing/ProgramImage";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { useProgramDetail, type PromoTier } from "@/lib/api/marketing";

import { cn } from "@/lib/utils";

/**
 * Program terms, opened one program at a time.
 *
 * The whole point of this dialog is the one number Grab never prints:
 * how much the store pays per discounted order. Grab shows "Giảm 12.000đ"
 * and "Grab đồng tài trợ 1.000đ" on separate lines and leaves the
 * subtraction to the reader, which is how a program funded at 8% reads
 * like a partnership. Here the store's own cost leads, and Grab's share
 * is shown as a percentage next to it.
 *
 * Every figure is derived from Vietnamese prose, so Grab's original
 * sentences stay visible underneath. If the parse is ever wrong, the
 * operator can see it is wrong instead of trusting a clean-looking number.
 */

/** Grab's placement codes, in the operator's words. */
const AD_KIND_LABELS: Record<string, string> = {
  CAROUSEL_AD: "Hiển thị ở carousel",
  SEARCH_AD: "Hiển thị khi tìm kiếm",
};

function vnd(value: number | null): string {
  if (value === null || value === undefined) return "—";
  return `${value.toLocaleString("vi-VN")}đ`;
}

/**
 * Colour by how much of the discount Grab actually carries.
 *
 * Thresholds match the advisor's brief: ≥50% is the bar the operator set
 * for "worth joining", 20–50% is a judgement call, below 20% means the
 * store is funding the promotion almost alone. Everything captured so far
 * has landed in the red band.
 */
function fundingTone(pct: number | null): string {
  if (pct === null) return "bg-(--color-surface-3) text-(--color-muted-foreground)";
  if (pct >= 0.5) return "bg-emerald-500/10 text-emerald-600";
  if (pct >= 0.2) return "bg-amber-500/10 text-amber-600";
  return "bg-red-500/10 text-red-600";
}

/**
 * The two funding figures, as money when it's known and as a share when
 * it isn't.
 *
 * A percentage tier has no fixed đồng cost — it rides on the item price —
 * so its money fields are legitimately null. But when Grab has stated it
 * funds none of the discount, the *split* is still fully known: 0% / 100%.
 * Leaving both boxes as "—" there threw away the single most important
 * fact about five of the six programs this store is offered.
 */
function fundingCells(tier: PromoTier): { grab: string; shop: string } {
  // A tier with a fixed đồng cost states both sides in đồng — that is the
  // number the operator actually pays per order.
  if (tier.grab_cofund_vnd !== null && tier.merchant_cost_vnd !== null) {
    return {
      grab: vnd(tier.grab_cofund_vnd),
      shop: vnd(tier.merchant_cost_vnd),
    };
  }
  // A percentage tier has no fixed đồng cost, so both sides switch to the
  // split. Units stay consistent within a row — "0đ / 100%" reads as two
  // unrelated facts.
  const pct = tier.grab_funded_pct;
  if (pct !== null) {
    return { grab: pctLabel(pct), shop: pctLabel(1 - pct) };
  }
  return {
    grab: tier.grab_cofund_vnd !== null ? vnd(tier.grab_cofund_vnd) : "—",
    shop: "—",
  };
}

/** `0` → "0%", `1` → "100%", `0.083` → "8.3%". */
function pctLabel(share: number): string {
  const v = share * 100;
  return `${Number.isInteger(v) ? v : v.toFixed(1)}%`;
}

/**
 * Render Grab's terms sentence, which arrives with a markdown link in it.
 *
 * Shown as-is it reads "…đồng ý với Điều khoản Dịch vụ dành [cho Đối tác
 * Nhà hàng của Grab](https://…)". Only `[text](url)` is handled, and only
 * for http(s) — this is legal text from an upstream payload, so anything
 * unrecognised stays plain text rather than being interpreted.
 */
function TermsText({ text }: { text: string }) {
  const parts: React.ReactNode[] = [];
  const re = /\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    parts.push(
      <a
        key={m.index}
        href={m[2]}
        target="_blank"
        rel="noopener noreferrer"
        className="underline hover:text-(--color-brand)"
      >
        {m[1]}
      </a>,
    );
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return <>{parts}</>;
}

function TierCard({ tier }: { tier: PromoTier }) {
  const pct = tier.grab_funded_pct;
  const cells = fundingCells(tier);

  return (
    <div className="rounded-lg border border-(--color-border) bg-(--color-surface-2) p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          {tier.category && (
            <div className="text-[11px] uppercase tracking-wide text-(--color-muted-foreground)">
              {tier.category}
            </div>
          )}
          <div className="text-sm font-medium text-(--color-foreground)">
            {tier.title || "(Không tên)"}
          </div>
        </div>
        <Badge
          variant="secondary"
          className={cn("shrink-0 font-mono", fundingTone(pct))}
          title="Phần Grab gánh trên tổng mức giảm"
        >
          {pct === null ? "Grab ?%" : `Grab ${pctLabel(pct)}`}
        </Badge>
      </div>

      {/* The three figures that decide the program. `merchant_cost_vnd`
          is the only one Grab does not state anywhere — it is the
          subtraction the operator would otherwise do by hand, per tier. */}
      <div className="mt-3 grid grid-cols-3 gap-2 text-center">
        {(
          [
            ["Đơn tối thiểu", vnd(tier.min_order_vnd), ""],
            ["Grab tài trợ", cells.grab, "text-emerald-600"],
            ["Shop chịu", cells.shop, "text-red-500"],
          ] as const
        ).map(([label, value, tone]) => (
          <div key={label} className="rounded-md bg-(--color-surface-3)/50 px-2 py-1.5">
            <div className="text-[10px] text-(--color-muted-foreground)">{label}</div>
            <div className={cn("font-mono text-sm font-semibold", tone)}>{value}</div>
          </div>
        ))}
      </div>

      {tier.discount_percent !== null && (
        <p className="mt-2 text-[11px] text-(--color-muted-foreground)">
          Giảm theo phần trăm ({tier.discount_percent}%
          {tier.discount_cap_vnd !== null
            ? `, tối đa ${vnd(tier.discount_cap_vnd)}`
            : ""}
          ) — số tiền shop chịu phụ thuộc giá món, không quy ra được một con số
          cố định.
        </p>
      )}

      {/* A figure that contradicts itself is worse than a missing one:
          it looks usable. Say so next to the numbers, not instead of them. */}
      {tier.parse_note && (
        <p className="mt-2 flex items-start gap-1.5 rounded-md bg-amber-500/10 p-2 text-[11px] text-amber-700 dark:text-amber-200">
          <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
          {tier.parse_note}
        </p>
      )}

      {tier.bullets.length > 0 && (
        <ul className="mt-2 space-y-0.5 border-t border-(--color-border) pt-2">
          {tier.bullets.map((b, i) => (
            <li key={i} className="text-[11px] text-(--color-muted-foreground)">
              • {b.content}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function ProgramDetailDialog({
  open,
  eventId,
  eventName,
  onClose,
}: {
  open: boolean;
  /** Kept non-null through the close animation — see MarketingClient. */
  eventId: string | null;
  eventName: string;
  onClose: () => void;
}) {
  const { data, isLoading, error } = useProgramDetail(eventId);

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="pr-6 text-base">
            {data?.name || eventName || "Chi tiết chương trình"}
          </DialogTitle>
          <DialogDescription className="flex flex-wrap items-center gap-1.5">
            {data && (
              <>
                {/* Keyed off `can_join`, not `is_eligible`. The detail
                    payload returns isEligible:false for every program the
                    store is actively being offered, so rendering it would
                    label all of them "Chưa đủ ĐK" and tell the operator
                    they can't join things they can. */}
                <Badge
                  variant={data.can_join ? "secondary" : "outline"}
                  className={cn(data.can_join && "bg-emerald-500/10 text-emerald-600")}
                >
                  {data.can_join ? "Có thể tham gia" : "Chưa mở tham gia"}
                </Badge>
                {data.is_promo_stacking && (
                  <Badge variant="outline" className="gap-1">
                    <Layers className="h-3 w-3" />
                    Cộng dồn khuyến mãi
                  </Badge>
                )}
                {/* Strict `=== false`: null means Grab's payload never
                    said either way, and "chưa rõ" must not be rendered as
                    "Grab không tài trợ". */}
                {data.is_grab_cofund === false && (
                  <Badge variant="outline" className="text-red-500">
                    Grab không đồng tài trợ
                  </Badge>
                )}
              </>
            )}
          </DialogDescription>
        </DialogHeader>

        {isLoading ? (
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-xs text-(--color-muted-foreground)">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Đang tải điều khoản từ Grab…
            </div>
            {[0, 1].map((i) => (
              <Skeleton key={i} className="h-28 w-full rounded-lg" />
            ))}
          </div>
        ) : error ? (
          <p className="rounded-lg border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-600">
            {error instanceof Error ? error.message : "Không tải được chi tiết."}
          </p>
        ) : data ? (
          <div className="space-y-4">
            {data.hero_image_url && (
              <ProgramImage
                src={data.hero_image_url}
                className="h-40 w-full rounded-lg"
                iconClassName="h-8 w-8"
              />
            )}
            {data.description && (
              <p className="text-xs text-(--color-muted-foreground)">
                {data.description}
              </p>
            )}

            {data.tiers.length > 0 ? (
              <div className="space-y-2">
                <h3 className="text-xs font-medium uppercase tracking-wide text-(--color-muted-foreground)">
                  Cơ cấu khuyến mãi
                </h3>
                {data.tiers.map((t, i) => (
                  <TierCard key={`${t.title}-${i}`} tier={t} />
                ))}
              </div>
            ) : (
              <p className="text-sm text-(--color-muted-foreground)">
                Grab không trả về cơ cấu khuyến mãi cho chương trình này.
              </p>
            )}

            {/* One line, not a card per placement. These carry no
                co-funding split, so as tiers they rendered a "Grab ?%"
                badge over three blank figures — noise that looked like
                missing data. */}
            {data.ad_placements.length > 0 && (
              <div className="rounded-lg border border-(--color-border) p-3">
                <h3 className="text-xs font-medium uppercase tracking-wide text-(--color-muted-foreground)">
                  Quảng cáo kèm theo
                </h3>
                {data.ad_placements.map((a, i) => (
                  <p key={i} className="mt-1 text-[11px] text-(--color-muted-foreground)">
                    {AD_KIND_LABELS[a.kind] ?? a.kind}: {a.title}
                    {a.subtitle ? ` · ${a.subtitle}` : ""}
                  </p>
                ))}
                <p className="mt-1.5 text-[11px] text-(--color-muted-foreground)">
                  Chi phí quảng cáo tính theo mục Chi phí bên dưới, không phải
                  theo từng đơn như mức giảm ở trên.
                </p>
              </div>
            )}

            {data.costs.length > 0 && (
              <div className="space-y-2">
                <h3 className="text-xs font-medium uppercase tracking-wide text-(--color-muted-foreground)">
                  Chi phí
                </h3>
                {data.costs.map((c, i) => (
                  <div
                    key={i}
                    className="rounded-lg border border-(--color-border) p-3"
                  >
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="text-sm text-(--color-foreground)">{c.title}</span>
                      <span className="font-mono text-sm font-semibold text-(--color-foreground)">
                        {c.fee || "—"}
                      </span>
                    </div>
                    {c.notes.map((n, j) => (
                      <p key={j} className="mt-1 text-[11px] text-(--color-muted-foreground)">
                        {n}
                      </p>
                    ))}
                  </div>
                ))}
              </div>
            )}

            {data.schedule.length > 0 && (
              <div className="space-y-2">
                <h3 className="text-xs font-medium uppercase tracking-wide text-(--color-muted-foreground)">
                  Thời gian &amp; đối tượng
                </h3>
                {data.schedule.map((s, i) => (
                  <div key={i} className="rounded-lg border border-(--color-border) p-3">
                    <div className="text-[11px] text-(--color-muted-foreground)">
                      {s.label}
                    </div>
                    <div className="text-sm text-(--color-foreground)">{s.content}</div>
                    {s.tags.length > 0 && (
                      <div className="mt-1.5 flex flex-wrap gap-1">
                        {s.tags.map((t, j) => (
                          <Badge key={j} variant="secondary" className="text-[10px]">
                            {t}
                          </Badge>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}

            {data.opt_in && (
              <div className="space-y-2 rounded-lg border border-(--color-border) p-3">
                <div className="text-xs font-medium text-(--color-foreground)">
                  {data.opt_in.cta || "Tham gia chiến dịch"}
                </div>
                {data.opt_in.terms && (
                  <p className="text-[11px] leading-relaxed text-(--color-muted-foreground)">
                    <TermsText text={data.opt_in.terms} />
                  </p>
                )}
                {/* No join button. The request Grab's app sends when this
                    is tapped hasn't been captured, and guessing a write
                    endpoint against a live store is how you end up with a
                    campaign you didn't mean to join. Read-only until the
                    capture exists. */}
                <p className="text-[11px] text-amber-600 dark:text-amber-300">
                  Hiện chỉ xem được điều khoản. Muốn bấm tham gia ngay từ
                  dashboard thì cần capture request lúc bấm nút này trong app
                  Grab Merchant.
                </p>
              </div>
            )}

            {/* Grab adds section types without notice. Saying so beats
                rendering a shorter page that looks complete. */}
            {data.unknown_sections.length > 0 && (
              <div className="flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 p-2.5 text-[11px] text-amber-700 dark:text-amber-200">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <span>
                  Grab còn gửi thêm mục chưa đọc được (
                  {Array.from(new Set(data.unknown_sections)).join(", ")}). Xem
                  bản đầy đủ trong app Grab Merchant trước khi tham gia.
                </span>
              </div>
            )}
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
