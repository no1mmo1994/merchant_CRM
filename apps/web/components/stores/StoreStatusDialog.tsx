"use client";

import * as React from "react";
import { toast } from "sonner";
import { Check, Loader2, Minus, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { ApiError } from "@/lib/api";
import {
  useStoreOpeningHours,
  useUpdateStoreStatus,
  type StoreStatusKind,
} from "@/lib/api/stores";

/* ----------------------------------------------------------------------- */
/*                              TYPES                                       */
/* ----------------------------------------------------------------------- */

/** Canonical 6 presets from `cuahang/setting_timecuahang.py`:
 *   1=Nghỉ 30 phút   →  30m
 *   2=Nghỉ 1 tiếng   →  1h
 *   3=Nghỉ 2 tiếng   →  2h
 *   4=Nghỉ hôm nay   →  today (23:59:59.999999 VN)
 *   5=Nghỉ 7 ngày    →  7d
 *   6=Nghỉ 30 ngày   →  30d
 * "Mở lại" is a separate surface (`RestoreRow`).
 */
type PausePreset = "30m" | "1h" | "2h" | "today" | "7d" | "30d";
type BusyPreset = number; // minutes — 5..60 in 5-min steps

interface StoreStatusDialogProps {
  merchantId: string;
  /** Optional trigger element — a button or anchor. Falls back to a default. */
  trigger?: React.ReactNode;
  /**
   * Open / close controlled externally. If absent the dialog manages
   * itself (via the trigger).
   */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}

/* ----------------------------------------------------------------------- */
/*                            PRESET HELPERS                                */
/* ----------------------------------------------------------------------- */

/** Vietnam is UTC+7 year-round (no DST). The merchant script enforces
 *  this exact tz to dodge client-clock drift.
 */
const VN_TZ_OFFSET_MIN = 7 * 60;

/** Two-digit pad helper for the offset string. */
const pad2 = (n: number) => String(n).padStart(2, "0");

/** "now" expressed as a `YYYY-MM-DD` VN-wall-clock date string.
 *  Used as the building block for `vnEndOfToday()` so the result is
 *  anchored to the **VN calendar day** regardless of the operator's
 *  browser timezone. We compute it from the UTC instant shifted by
 *  the VN offset, then read the resulting Y/M/D via the round-tripped
 *  Date's UTC accessors — that gives the VN calendar day even when the
 *  browser is in another timezone.
 */
function vnTodayYmd(): { y: number; m: number; d: number } {
  const local = new Date();
  const vnMs = local.getTime() + VN_TZ_OFFSET_MIN * 60_000;
  const vn = new Date(vnMs);
  return {
    y: vn.getUTCFullYear(),
    m: vn.getUTCMonth(),
    d: vn.getUTCDate(),
  };
}

/** Add N minutes to "now" — returns a real UTC instant ("now + min")
 *  as a `Date`. Same instant as the clock on the wall, no timezone
 *  gymnastics needed. Used for the 1h / 2h / 30d presets where the
 *  delta is what matters, not the calendar boundary.
 */
function vnNowPlus(minutes: number): Date {
  return new Date(Date.now() + minutes * 60_000);
}

/** End-of-day in VN wall clock (23:59:59.999999), returned as a `Date`
 *  whose underlying instant is **the right UTC moment** no matter what
 *  timezone the operator's browser lives in.
 *
 *  Why the explicit "+07:00" suffix: `new Date("2026-08-04T23:59:59.999+07:00")`
 *  is parsed by the JS engine as a fixed instant in time. The browser's
 *  own timezone has zero influence on the parsed result, which is what
 *  we need — otherwise a Europe-timezone operator would compute "VN
 *  midnight" 6 hours off, and Grab would auto-resume the store at the
 *  wrong instant.
 *
 *  Microsecond = 999999 — matches `setting_timecuahang.py`:
 *      end_time_utc.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
 */
function vnEndOfToday(): Date {
  const { y, m, d } = vnTodayYmd();
  const iso = `${y}-${pad2(m + 1)}-${pad2(d)}T23:59:59.999999+07:00`;
  return new Date(iso);
}

function pauseEndDate(preset: PausePreset): Date {
  switch (preset) {
    case "30m":
      return vnNowPlus(30);
    case "1h":
      return vnNowPlus(60);
    case "2h":
      return vnNowPlus(2 * 60);
    case "today":
      return vnEndOfToday();
    case "7d":
      return vnNowPlus(7 * 24 * 60);
    case "30d":
      return vnNowPlus(30 * 24 * 60);
  }
}

/** Final UTC ISO-8601 string with the `Z` suffix Grab expects. The
 *  input `Date` is already a real UTC instant — `Date.prototype
 *  .toISOString()` always emits `Z`, no further work needed. (The
 *  previous version of this helper did a hand-rolled `-7h` adjustment
 *  that double-subtracted the VN offset on `vnNowPlus` results — that
 *  sent `tempPauseEnd` 7 hours into the past for 1h/2h/30d and 7 hours
 *  short for "today", which is exactly the class of 409s the operator
 *  reported. Both helpers now produce the correct UTC instant up front,
 *  so this is a straight pass-through.)
 */
function toUtcIso(instant: Date): string {
  return instant.toISOString();
}

/* ----------------------------------------------------------------------- */
/*                              COMPONENT                                   */
/* ----------------------------------------------------------------------- */

/**
 * "Đặt trạng thái quán" — mirror of Grab's mobile dialog.
 *
 * Two surfaces share this dialog:
 *   1. **Đang bận** (BUSY) — 15 / 30 / 60 minute prep-time.
 *   2. **Tạm nghỉ** (TEMPPAUSED) — 30 phút / 1 tiếng / 2 tiếng /
 *      hôm nay / 7 ngày / 30 ngày, plus "Mở lại".
 *
 * Selecting any preset fires `POST /api/stores/{merchantId}/status`
 * with the matching `kind`/`minutes`/`pause_end_utc`.
 *
 * "Mở lại cửa hàng" sends `unpause: true` which exits whichever state
 * Grab currently has the store in (BUSY → NORMAL or TEMPPAUSED → NORMAL).
 *
 * Auth wiring: the dashboard never hard-codes the Grab `authorization`
 * / `x-mts-ssid` JWTs. Every successful login (`POST /api/auth/login`)
 * rotates the encrypted `authn_token` stored on the Store row, and the
 * `GrabClient._headers()` helper injects the freshest token on every
 * outgoing request — so the dashboard's headers always match whatever
 * the merchant app most recently negotiated with Grab.
 */
export function StoreStatusDialog({
  merchantId,
  trigger,
  open: controlledOpen,
  onOpenChange: controlledOnOpenChange,
}: StoreStatusDialogProps) {
  const [internalOpen, setInternalOpen] = React.useState(false);
  const isControlled = controlledOpen !== undefined;
  const open = isControlled ? controlledOpen : internalOpen;
  const setOpen = (v: boolean) => {
    if (!isControlled) setInternalOpen(v);
    controlledOnOpenChange?.(v);
  };

  const mutation = useUpdateStoreStatus(merchantId);
  const [pendingKind, setPendingKind] = React.useState<StoreStatusKind | null>(null);
  const [pendingPreset, setPendingPreset] = React.useState<string | null>(null);

  // Live runtime state from `GET /food/merchant/v3/open-status` (same
  // source as the dashboard's `StoreStatusCard` pill). We pass it to
  // the backend on every mutation so it can pick the right
  // `fromState` for Grab's `PUT /food/merchant/v1/merchant/status` —
  // without this the backend always sends `fromState: "NORMAL"` and
  // Grab 409's the request the moment the store is actually in BUSY /
  // TEMPPAUSED. `null` is the safe fallback (server maps it to
  // `NORMAL` — same as the old hard-coded behaviour).
  const { data: hours } = useStoreOpeningHours(merchantId);
  const currentRuntime = hours?.data.status_label ?? null;

  // Reset pending state when the dialog closes so reopening starts fresh.
  React.useEffect(() => {
    if (!open) {
      setPendingKind(null);
      setPendingPreset(null);
    }
  }, [open]);

  const busy = mutation.isPending || pendingKind !== null;

  async function applyPause(preset: PausePreset) {
    setPendingKind("temp_pause");
    setPendingPreset(preset);
    try {
      const pause_end_utc = toUtcIso(pauseEndDate(preset));
      await mutation.mutateAsync({
        kind: "temp_pause",
        unpause: false,
        pause_end_utc,
        current_runtime: currentRuntime,
      });
      toast.success(pauseSuccessMessage(preset));
      setOpen(false);
    } catch (err) {
      toast.error(errorMessage(err, "Tạm nghỉ thất bại"));
    } finally {
      setPendingKind(null);
      setPendingPreset(null);
    }
  }

  async function applyBusy(minutes: BusyPreset) {
    setPendingKind("busy");
    setPendingPreset(String(minutes));
    try {
      await mutation.mutateAsync({
        kind: "busy",
        unpause: false,
        minutes: minutes as 15 | 30 | 60,
        current_runtime: currentRuntime,
      });
      toast.success(`Đã đặt chế độ bận ${minutes} phút`);
      setOpen(false);
    } catch (err) {
      toast.error(errorMessage(err, "Đặt chế độ bận thất bại"));
    } finally {
      setPendingKind(null);
      setPendingPreset(null);
    }
  }

  async function applyUnpause() {
    // Pick the right helper for the current state. Grab's
    // `PUT /food/merchant/v1/merchant/status` requires `fromState`
    // to match what's actually in the merchant app:
    //
    //   BUSY        → kind="busy" + unpause=true  (busy_unpause path)
    //   TEMPPAUSED  → kind="temp_pause" + unpause=true
    //   OPEN        → no-op (the dialog should even be hidden in
    //                   this case, but guard anyway)
    //
    // The backend now ALSO fetches `v3/open-status` if it doesn't trust
    // `current_runtime`, but dispatching to the matching helper from
    // the client makes the audit log + retry semantics cleaner.
    const kind: StoreStatusKind =
      currentRuntime === "Paused" ? "temp_pause" : "busy";
    setPendingKind(kind);
    setPendingPreset("unpause");
    try {
      await mutation.mutateAsync({
        kind,
        unpause: true,
        current_runtime: currentRuntime,
      });
      toast.success("Đã mở cửa hoạt động bình thường");
      setOpen(false);
    } catch (err) {
      toast.error(errorMessage(err, "Mở cửa thất bại"));
    } finally {
      setPendingKind(null);
      setPendingPreset(null);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      {trigger ? (
        <span
          onClick={() => setOpen(true)}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              setOpen(true);
            }
          }}
        >
          {trigger}
        </span>
      ) : (
        <Button
          size="sm"
          onClick={() => setOpen(true)}
          className="bg-(--color-brand) text-white hover:bg-(--color-brand-hover)"
        >
          Đặt trạng thái quán
        </Button>
      )}

      <DialogContent className="max-h-[90vh] w-[calc(100vw-2rem)] overflow-y-auto sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="text-2xl font-bold">Đặt trạng thái quán</DialogTitle>
        </DialogHeader>

        <div className="rounded-xl border border-(--color-border) bg-(--color-surface) p-1">
          {/* Đang bận (BUSY) — prep time +/- stepper, default 15 min */}
          <BusyRow
            busy={busy && pendingKind === "busy" && pendingPreset !== "unpause"}
            onSubmit={applyBusy}
          />

          <div className="mx-3 border-t border-(--color-border)" />

          {/* Tạm nghỉ (TEMPPAUSED) — preset chip grid */}
          <PauseRow
            busy={busy && pendingKind === "temp_pause"}
            pendingPreset={pendingPreset}
            onSubmit={applyPause}
          />

          <div className="mx-3 border-t border-(--color-border)" />

          {/* Mở lại */}
          <RestoreRow
            busy={busy && pendingPreset === "unpause"}
            onSubmit={applyUnpause}
          />
        </div>

        <p className="px-1 text-center text-sm text-(--color-muted-foreground)">
          Bạn muốn điều chỉnh khung giờ hoạt động?{" "}
          <a className="font-medium text-(--color-brand) hover:underline" href="/settings">
            Cập nhật khung giờ hoạt động
          </a>
        </p>

        <DialogFooter className="-mx-4 -mb-4 mt-2 sm:justify-center">
          <Button
            type="button"
            disabled={busy}
            onClick={() => setOpen(false)}
            className="w-full bg-(--color-brand) text-white hover:bg-(--color-brand-hover) sm:w-2/3"
          >
            Xác nhận
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/* ----------------------------------------------------------------------- */
/*                                ROWS                                      */
/* ----------------------------------------------------------------------- */

interface BusyRowProps {
  busy: boolean;
  onSubmit: (minutes: BusyPreset) => void;
}

/**
 * "Đang bận" row — busy prepare time +/- stepper.
 *
 * Steps 15..60 in 5-min increments (matches Grab mobile). We then
 * forward only the canonical 15 / 30 / 60 values to the backend; any
 * other value falls back to the nearest canonical step.
 */
function BusyRow({ busy, onSubmit }: BusyRowProps) {
  const [minutes, setMinutes] = React.useState<BusyPreset>(15);
  const clamp = (n: number): BusyPreset => {
    if (n <= 15) return 15;
    if (n >= 60) return 60;
    return n;
  };

  return (
    <div className="space-y-3 p-3">
      <div className="flex items-center gap-3">
        <span className="h-3 w-3 rounded-full bg-amber-500" />
        <div>
          <div className="text-base font-medium">Đang bận</div>
          <div className="text-sm text-(--color-muted-foreground)">
            Bạn cần bao nhiêu thời gian để có thể chuẩn bị đơn hàng mới?
          </div>
        </div>
      </div>

      {/* Stepper — visually identical to the Grab mobile dialog (– 15 +) */}
      <div className="flex items-center justify-center gap-6 py-2">
        <button
          type="button"
          aria-label="Giảm 5 phút"
          disabled={busy || minutes <= 15}
          onClick={() => setMinutes(clamp(minutes - 5))}
          className={cn(
            "flex h-12 w-12 items-center justify-center rounded-full border border-(--color-border) bg-(--color-surface)",
            "disabled:opacity-30",
            "hover:border-(--color-brand) hover:bg-(--color-brand)/5",
          )}
        >
          <Minus className="h-5 w-5" />
        </button>
        <div className="min-w-[5rem] text-center text-2xl font-semibold tabular-nums">
          {minutes} phút
        </div>
        <button
          type="button"
          aria-label="Tăng 5 phút"
          disabled={busy || minutes >= 60}
          onClick={() => setMinutes(clamp(minutes + 5))}
          className={cn(
            "flex h-12 w-12 items-center justify-center rounded-full bg-emerald-100 text-emerald-700",
            "disabled:opacity-30",
            "hover:bg-emerald-200",
          )}
        >
          <Plus className="h-5 w-5" />
        </button>
      </div>

      <Button
        type="button"
        onClick={() => onSubmit(minutes)}
        disabled={busy}
        className="w-full bg-amber-500 text-white hover:bg-amber-600"
      >
        {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
        {busy ? "Đang lưu…" : "Đặt chế độ bận"}
      </Button>
    </div>
  );
}

interface PauseRowProps {
  busy: boolean;
  pendingPreset: string | null;
  onSubmit: (preset: PausePreset) => void;
}

const PAUSE_CHIPS: { label: string; preset: PausePreset }[] = [
  { label: "30 phút", preset: "30m" },
  { label: "1 tiếng", preset: "1h" },
  { label: "2 tiếng", preset: "2h" },
  { label: "Hôm nay", preset: "today" },
  { label: "7 ngày", preset: "7d" },
  { label: "30 ngày", preset: "30d" },
];

/**
 * "Tạm nghỉ" row — preset chip grid + the actual "Tạm nghỉ" submit.
 *
 * Layout (mirrors `cuahang/setting_timecuahang.py` exactly):
 *   30 phút · 1 tiếng · 2 tiếng · Hôm nay · 7 ngày · 30 ngày
 */
function PauseRow({ busy, pendingPreset, onSubmit }: PauseRowProps) {
  const [selected, setSelected] = React.useState<PausePreset>("30m");

  return (
    <div className="space-y-3 p-3">
      <div className="flex items-center gap-3">
        <span className="h-3 w-3 rounded-full bg-red-500" />
        <div>
          <div className="text-base font-medium">Tạm nghỉ</div>
          <div className="text-sm text-(--color-muted-foreground)">
            Bạn muốn tạm ngưng nhận đơn hàng đến trong bao lâu?
          </div>
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        {PAUSE_CHIPS.map((c) => {
          const active = c.preset === selected;
          const isPending = busy && pendingPreset === c.preset;
          return (
            <button
              key={c.label}
              type="button"
              onClick={() => setSelected(c.preset)}
              disabled={busy}
              className={cn(
                "rounded-full border px-4 py-2 text-sm font-medium transition",
                active
                  ? "border-emerald-500 bg-emerald-100 text-emerald-700"
                  : "border-(--color-border) bg-(--color-surface) text-(--color-foreground) hover:border-(--color-brand)",
                isPending && "opacity-60",
              )}
            >
              {c.label}
            </button>
          );
        })}
      </div>

      <Button
        type="button"
        onClick={() => onSubmit(selected)}
        disabled={busy}
        className="w-full bg-red-500 text-white hover:bg-red-600"
      >
        {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
        {busy ? "Đang lưu…" : "Tạm nghỉ"}
      </Button>
    </div>
  );
}

interface RestoreRowProps {
  busy: boolean;
  onSubmit: () => void;
}

/**
 * "Mở lại cửa hàng" — exit any paused/busy state.
 */
function RestoreRow({ busy, onSubmit }: RestoreRowProps) {
  return (
    <div className="space-y-3 p-3">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="h-3 w-3 rounded-full bg-emerald-500" />
          <div>
            <div className="text-base font-medium">Mở lại cửa hàng</div>
            <div className="text-sm text-(--color-muted-foreground)">
              Trở về trạng thái hoạt động bình thường (NORMAL).
            </div>
          </div>
        </div>
        <Check className="h-5 w-5 text-emerald-500" />
      </div>

      <Button
        type="button"
        onClick={onSubmit}
        disabled={busy}
        className="w-full bg-emerald-600 text-white hover:bg-emerald-700"
      >
        {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
        {busy ? "Đang lưu…" : "Mở lại"}
      </Button>
    </div>
  );
}

/* ----------------------------------------------------------------------- */
/*                              HELPERS                                     */
/* ----------------------------------------------------------------------- */

function pauseSuccessMessage(preset: PausePreset): string {
  switch (preset) {
    case "30m":
      return "Đã tạm nghỉ 30 phút";
    case "1h":
      return "Đã tạm nghỉ 1 tiếng";
    case "2h":
      return "Đã tạm nghỉ 2 tiếng";
    case "today":
      return "Đã tạm nghỉ đến cuối ngày";
    case "7d":
      return "Đã tạm nghỉ 7 ngày";
    case "30d":
      return "Đã tạm nghỉ 30 ngày";
  }
}

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return fallback;
}
