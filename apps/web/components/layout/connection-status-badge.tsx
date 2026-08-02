"use client";

import * as React from "react";
import { AlertCircle, Loader2, RadioTower } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  type StoreConnectionStatus,
  useStoreConnectionStatus,
} from "@/hooks/useStoreConnectionStatus";

interface ConnectionStatusBadgeProps {
  /**
   * When `false`, the badge still renders but the icon animation
   * (pulsing dot / spinner) is paused — used by the error variant
   * where animation would distract from the red colour.
   */
  className?: string;
}

/**
 * Tiny live status pill shown in the topbar. Reads
 * `useStoreConnectionStatus` and renders one of:
 *  - "Đang hoạt động"    (green dot, pulsing)  → store is ACTIVE on Grab
 *  - "Đang kiểm tra…"   (spinner)             → first poll in flight
 *  - "Lỗi AuthToken"    (amber alert)        → 3+ failed polls, token likely dead
 *
 * The whole pill is also a link to Settings, so a user seeing
 * "Lỗi AuthToken" can click → land on Settings → refresh token →
 * badge clears on next poll.
 */
export function ConnectionStatusBadge({ className }: ConnectionStatusBadgeProps) {
  const { status, merchantId } = useStoreConnectionStatus();
  return (
    <span
      role="status"
      aria-live="polite"
      data-testid="connection-status"
      data-status={status}
      className={cn(
        "inline-flex h-9 items-center gap-1.5 rounded-full border px-3 text-xs font-medium",
        status === "active" &&
          "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
        status === "loading" &&
          "border-zinc-500/40 bg-zinc-500/10 text-zinc-700 dark:text-zinc-300",
        status === "authtoken_error" &&
          "border-amber-500/50 bg-amber-500/10 text-amber-700 dark:text-amber-300",
        className,
      )}
      title={merchantId ? `Merchant: ${merchantId}` : undefined}
    >
      {status === "active" ? (
        <>
          <span className="relative flex h-2.5 w-2.5">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
            <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-emerald-500" />
          </span>
          Đang hoạt động
        </>
      ) : status === "authtoken_error" ? (
        <>
          <AlertCircle className="h-3.5 w-3.5" aria-hidden />
          Lỗi AuthToken
        </>
      ) : (
        <>
          {status === "loading" ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
          ) : (
            <RadioTower className="h-3.5 w-3.5" aria-hidden />
          )}
          Đang kiểm tra…
        </>
      )}
    </span>
  );
}

export { type StoreConnectionStatus };
