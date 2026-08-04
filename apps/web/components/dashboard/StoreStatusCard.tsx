"use client";

import * as React from "react";
import { Activity, AlertCircle, Coffee, PowerOff } from "lucide-react";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useUIStore } from "@/lib/stores/ui-store";
import { useAuthStore } from "@/lib/stores/auth-store";
import { useStoreOpeningHours, useStores } from "@/lib/api/stores";
import { fadeUp } from "@/lib/animations/variants";
import { motion } from "framer-motion";
import { cn } from "@/lib/utils";
import { StoreStatusDialog } from "@/components/stores/StoreStatusDialog";

/**
 * Live runtime status card.
 *
 * Mirrors `cuahang/trangthai2.py` via `GET /food/merchant/v3/open-status`
 * and renders three things on a single row:
 *
 *   * A three-state pill (Open / BusyMode / Paused) — the same chip
 *     the Grab merchant app shows on its home screen.
 *   * A "Đặt trạng thái quán" trigger button (`StoreStatusDialog`),
 *     inline with the pill so the merchant sees the current state and
 *     the action button at a glance.
 *   * A note bar under the row quoting Grab's verbatim
 *     `status_content` plus a Vietnamese sentence describing the
 *     runtime state (e.g. "Đang mở cửa · Đang mở cửa").
 *
 * The previous version of this card also rendered an account-level
 * status section (ACTIVE / PENDING / SUSPENDED) with an auth-token
 * banner; both have been removed at the operator's request so the
 * "Trạng thái cửa hàng" card is now a single-purpose runtime panel.
 */
export function StoreStatusCard() {
  const activeStoreId = useUIStore((s) => s.activeStoreId);
  const authStores = useAuthStore((s) => s.stores);
  const { data: storesData } = useStores();
  const stores = storesData ?? authStores;
  const activeStore = stores.find((s) => String(s.id) === activeStoreId) ?? stores[0];
  const merchantId = activeStore?.merchant_id ?? null;

  const { data: hours, isLoading: hoursLoading } =
    useStoreOpeningHours(merchantId);

  return (
    <motion.div variants={fadeUp} className="lg:col-span-12">
      <Card className="border-(--color-border)">
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="space-y-1.5">
              <div className="flex items-center gap-2">
                <Activity className="h-4 w-4 text-(--color-brand)" />
                <CardTitle>Trạng thái cửa hàng</CardTitle>
              </div>
              <CardDescription>
                Trạng thái runtime realtime (Mở cửa / Bận / Tạm nghỉ) từ
                endpoint <span className="font-mono">v3/open-status</span>{" "}
                của Grab. Cập nhật tự động mỗi 30 giây.
              </CardDescription>
            </div>

            {/* Right-hand cluster — pill + action button share one row
                so the operator sees the current state and the trigger
                to change it at a glance. */}
            {merchantId && (
              <div className="flex flex-wrap items-center gap-2">
                <RuntimePill
                  label={hours?.data.status_label ?? null}
                  isOpen={hours?.data.is_open ?? null}
                  loading={hoursLoading}
                />
                <StoreStatusDialog
                  merchantId={merchantId}
                  trigger={
                    <button
                      type="button"
                      className="inline-flex items-center gap-1.5 rounded-md bg-(--color-brand) px-3 py-1.5 text-xs font-medium text-white shadow-sm transition hover:bg-(--color-brand-hover)"
                    >
                      Đặt trạng thái quán
                    </button>
                  }
                />
              </div>
            )}
          </div>

          {/* Operator note — verbatim `status_content` from Grab plus a
              Vietnamese sentence describing the runtime state. Sits
              right under the pill so the merchant always sees what
              state the store is in and when it resumes. */}
          {merchantId && !hoursLoading && hours?.data.status_content && (
            <div
              className={cn(
                "mt-3 flex items-start gap-2 rounded-md border px-3 py-2 text-xs",
                hours.data.status_label === "Open" &&
                  "border-emerald-500/30 bg-emerald-50/50 text-emerald-800 dark:bg-emerald-500/10 dark:text-emerald-200",
                hours.data.status_label === "BusyMode" &&
                  "border-amber-500/40 bg-amber-50/50 text-amber-800 dark:bg-amber-500/10 dark:text-amber-200",
                hours.data.status_label === "Paused" &&
                  "border-red-500/30 bg-red-50/50 text-red-700 dark:bg-red-500/10 dark:text-red-200",
                !hours.data.status_label &&
                  "border-(--color-border) text-(--color-muted-foreground)",
              )}
              title={hours.data.status_note ?? hours.data.status_content}
            >
              <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span className="leading-relaxed">
                <strong className="font-semibold">
                  {runtimeNotePrefix(hours.data.status_label)}
                </strong>
                {hours.data.status_content
                  ? ` · ${hours.data.status_content}`
                  : ""}
              </span>
            </div>
          )}
        </CardHeader>
      </Card>
    </motion.div>
  );
}

function runtimeNotePrefix(
  label: "Open" | "BusyMode" | "Paused" | null | undefined,
): string {
  switch (label) {
    case "Open":
      return "Đang mở cửa";
    case "BusyMode":
      return "Đang bận";
    case "Paused":
      return "Đang tạm nghỉ";
    default:
      return "Trạng thái";
  }
}

interface RuntimePillProps {
  label: "Open" | "BusyMode" | "Paused" | null | undefined;
  isOpen: boolean | null | undefined;
  loading: boolean;
}

/**
 * Three-state runtime pill (mirrors `cuahang/trangthai2.py`):
 *   Open      → green pulsing "ĐANG MỞ CỬA"
 *   BusyMode  → amber "ĐANG BẬN"
 *   Paused    → red "ĐANG TẠM NGHỈ / ĐÓNG CỬA"
 *
 * Falls back to the boolean `is_open` (from v2/merchants) when the
 * v3 label is missing — better green-than-grey than nothing.
 */
function RuntimePill({ label, isOpen, loading }: RuntimePillProps) {
  if (loading) {
    return <Skeleton className="h-7 w-32" />;
  }
  if (label === "Open") return <OpenPill />;
  if (label === "BusyMode") return <BusyPill />;
  if (label === "Paused") return <ClosedPill />;
  if (isOpen === true) return <OpenPill />;
  if (isOpen === false) return <ClosedPill />;
  return <Badge variant="secondary">—</Badge>;
}

function OpenPill() {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-300">
      <span className="relative flex h-2 w-2">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
      </span>
      ĐANG MỞ CỬA
    </span>
  );
}

function BusyPill() {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-800 dark:bg-amber-500/20 dark:text-amber-200">
      <Coffee className="h-3.5 w-3.5" />
      ĐANG BẬN
    </span>
  );
}

function ClosedPill() {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-red-100 px-3 py-1 text-xs font-semibold text-red-700 dark:bg-red-500/20 dark:text-red-300">
      <PowerOff className="h-3.5 w-3.5" />
      ĐANG TẠM NGHỈ / ĐÓNG CỬA
    </span>
  );
}
