"use client";

import { Sparkles, Repeat } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

/**
 * "Khách mới" / "Khách quay lại", from Grab's `flags.isPaxNewCustomer`.
 *
 * Three states, not two. `null` means Grab sent no flag, and it renders
 * nothing at all — labelling such an order "khách quay lại" would assert
 * something about the customer that Grab never said, and on a screen
 * meant to measure customer acquisition a wrong label is worse than a
 * missing one.
 *
 * Grab's flag is worth more than anything the dashboard could compute
 * from its own archive: it reflects the eater's entire history with the
 * store, including every order placed before this dashboard existed.
 */
export function CustomerTypeBadge({
  isNew,
  className,
}: {
  isNew: boolean | null | undefined;
  className?: string;
}) {
  if (isNew === null || isNew === undefined) return null;

  if (isNew) {
    return (
      <Badge
        variant="secondary"
        className={cn("gap-1 bg-emerald-500/10 text-emerald-600", className)}
        title="Grab đánh dấu đây là đơn đầu tiên của khách này tại cửa hàng"
      >
        <Sparkles className="h-3 w-3" />
        Khách mới
      </Badge>
    );
  }

  return (
    <Badge
      variant="outline"
      className={cn("gap-1 text-(--color-muted-foreground)", className)}
      title="Khách đã từng đặt tại cửa hàng trước đó"
    >
      <Repeat className="h-3 w-3" />
      Khách quay lại
    </Badge>
  );
}
