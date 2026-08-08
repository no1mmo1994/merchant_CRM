"use client";

import { HelpCircle, Repeat, Sparkles } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import type { CustomerMix, CustomerMixBucket } from "@/lib/api/customers";
import { cn } from "@/lib/utils";

/**
 * New versus returning customers — the trading question behind the order
 * list.
 *
 * Each slice shows orders, distinct customers, revenue and average order
 * value, because "how many" and "how much each" answer different things:
 * a store can take most of its orders from new faces while returning
 * customers quietly spend more per basket, and only the two side by side
 * make that visible.
 *
 * Cancelled orders are shown but excluded from revenue and from the
 * average. They say something about demand; counting their totals as
 * takings would not.
 */

function formatVnd(value: number): string {
  return `${Math.round(value).toLocaleString("vi-VN")}₫`;
}

function Slice({
  label,
  hint,
  icon,
  bucket,
  tone,
  share,
}: {
  label: string;
  hint: string;
  icon: React.ReactNode;
  bucket: CustomerMixBucket;
  tone: string;
  share: number | null;
}) {
  const counted = bucket.orders - bucket.cancelledOrders;

  return (
    <div className="rounded-lg border border-(--color-border) bg-(--color-surface-2) p-3">
      <div className="flex items-center justify-between gap-2">
        <span className={cn("inline-flex items-center gap-1.5 text-xs font-medium", tone)}>
          {icon}
          {label}
        </span>
        {share !== null && (
          <span className="font-mono text-xs text-(--color-muted-foreground)">
            {(share * 100).toFixed(0)}% đơn
          </span>
        )}
      </div>

      <div className="mt-2 flex items-baseline gap-1.5">
        <span className="text-xl font-semibold text-(--color-foreground)">
          {bucket.orders}
        </span>
        <span className="text-xs text-(--color-muted-foreground)">đơn</span>
        {bucket.cancelledOrders > 0 && (
          <span className="text-xs text-red-500">
            ({bucket.cancelledOrders} huỷ)
          </span>
        )}
      </div>

      <dl className="mt-2 space-y-0.5 text-xs text-(--color-muted-foreground)">
        <div className="flex justify-between gap-2">
          <dt>Khách</dt>
          <dd className="font-medium text-(--color-foreground)">
            {bucket.customers}
          </dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt>Doanh thu</dt>
          <dd className="font-medium text-(--color-foreground)">
            {counted > 0 ? formatVnd(bucket.revenueVnd) : "—"}
          </dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt>TB/đơn</dt>
          <dd className="font-medium text-(--color-foreground)">
            {counted > 0 ? formatVnd(bucket.avgOrderValue) : "—"}
          </dd>
        </div>
      </dl>

      <p className="mt-2 border-t border-(--color-border) pt-1.5 text-[11px] leading-snug text-(--color-muted-foreground)">
        {hint}
      </p>
    </div>
  );
}

export function CustomerMixCard({ mix }: { mix: CustomerMix }) {
  const total = mix.new.orders + mix.returning.orders + mix.unknown.orders;
  if (total === 0) return null;

  const newAov = mix.new.avgOrderValue;
  const returningAov = mix.returning.avgOrderValue;
  // Only worth a sentence when both sides actually traded — comparing
  // against a slice with no completed orders would read as a finding.
  const canCompare =
    mix.new.orders - mix.new.cancelledOrders > 0 &&
    mix.returning.orders - mix.returning.cancelledOrders > 0;

  return (
    <Card className="border-(--color-border)">
      <CardContent className="space-y-3 p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-sm font-medium text-(--color-foreground)">
            Khách mới &amp; khách quay lại
          </h2>
          <span className="text-xs text-(--color-muted-foreground)">
            Theo nhãn của Grab trên từng đơn
          </span>
        </div>

        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          <Slice
            label="Khách mới"
            hint="Đơn đầu tiên của khách tại cửa hàng — chi phí để có được họ nằm ở các chương trình khuyến mãi."
            icon={<Sparkles className="h-3.5 w-3.5" />}
            tone="text-emerald-600"
            bucket={mix.new}
            share={mix.newOrderShare}
          />
          <Slice
            label="Khách quay lại"
            hint="Khách đã từng đặt trước đó — không tốn chi phí thu hút, phần lợi nhuận giữ được nhiều hơn."
            icon={<Repeat className="h-3.5 w-3.5" />}
            tone="text-(--color-foreground)"
            bucket={mix.returning}
            share={mix.newOrderShare === null ? null : 1 - mix.newOrderShare}
          />
          {/* Only shown when it exists. A permanent empty "chưa rõ" box
              would suggest a problem where there isn't one. */}
          {mix.unknown.orders > 0 && (
            <Slice
              label="Chưa rõ"
              hint="Grab không gửi nhãn cho những đơn này. Không xếp vào khách cũ để tránh kết luận sai."
              icon={<HelpCircle className="h-3.5 w-3.5" />}
              tone="text-(--color-muted-foreground)"
              bucket={mix.unknown}
              share={null}
            />
          )}
        </div>

        {canCompare && (
          <p className="text-xs text-(--color-muted-foreground)">
            {returningAov > newAov ? (
              <>
                Khách quay lại chi{" "}
                <strong className="text-(--color-foreground)">
                  {formatVnd(returningAov - newAov)}
                </strong>{" "}
                mỗi đơn nhiều hơn khách mới — giữ chân khách đang có giá trị hơn
                là chạy khuyến mãi hút khách mới.
              </>
            ) : newAov > returningAov ? (
              <>
                Khách mới chi{" "}
                <strong className="text-(--color-foreground)">
                  {formatVnd(newAov - returningAov)}
                </strong>{" "}
                mỗi đơn nhiều hơn khách quay lại.
              </>
            ) : (
              <>Giá trị trung bình mỗi đơn của hai nhóm ngang nhau.</>
            )}
            {mix.newRevenueShare !== null && (
              <>
                {" "}
                Khách mới đóng góp{" "}
                <strong className="text-(--color-foreground)">
                  {(mix.newRevenueShare * 100).toFixed(0)}%
                </strong>{" "}
                doanh thu.
              </>
            )}
          </p>
        )}

        {/* The archive is the dashboard's own polling history, not
            Grab's full ledger — saying so stops the numbers being read
            as lifetime totals. */}
        <p className="text-[11px] text-(--color-muted-foreground)">
          Tính trên các đơn dashboard đã ghi nhận, không phải toàn bộ lịch sử
          cửa hàng.
        </p>
      </CardContent>
    </Card>
  );
}
