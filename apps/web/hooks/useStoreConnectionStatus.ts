"use client";

import * as React from "react";
import { useStores, useStoreStatus } from "@/lib/api/stores";
import { useAuthStore } from "@/lib/stores/auth-store";
import { useUIStore } from "@/lib/stores/ui-store";

/**
 * Real-time connection status used by the topbar pill + StoreStatusCard.
 *
 * Three buckets:
 *  - "active"  : store is connected + reachable + ACTIVE on Grab.
 *  - "loading" : first request still in flight.
 *  - "authtoken_error": repeated failures to reach Grab for the active
 *    store's status endpoint. Once the same store fails 3 times in a
 *    row (or returns 401 multiple times) we assume the local auth
 *    token is dead and surface an explicit "Lỗi AuthToken" state so
 *    the user knows to refresh it from Settings, instead of just
 *    showing "Đang hoạt động" forever (the old v1 behaviour) or a
 *    silent gray dot.
 */
export type StoreConnectionStatus = "active" | "loading" | "authtoken_error";

const STORAGE_KEY = "pulseorder.authtoken-fail-streak";

interface FailStreakMap {
  [merchantId: string]: { count: number; firstAt: number };
}

function loadFailStreak(): FailStreakMap {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as FailStreakMap;
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function saveFailStreak(map: FailStreakMap) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(map));
  } catch {
    // ignore quota / private-mode errors — best-effort only.
  }
}

/**
 * Lightweight hook that derives the live status badge for the
 * currently-selected store. Re-computes whenever the store query
 * data / status query data / status polling state changes.
 */
export function useStoreConnectionStatus(): {
  status: StoreConnectionStatus;
  merchantId: string | null;
} {
  const activeStoreId = useUIStore((s) => s.activeStoreId);
  const authStores = useAuthStore((s) => s.stores);
  const { data: storesData } = useStores();
  const stores = storesData ?? authStores;
  const activeStore =
    stores.find((s) => String(s.id) === activeStoreId) ?? stores[0];
  const merchantId = activeStore?.merchant_id ?? null;

  const statusQuery = useStoreStatus(merchantId);

  const streakRef = React.useRef<FailStreakMap>({});
  const [tick, setTick] = React.useState(0);
  React.useEffect(() => {
    streakRef.current = loadFailStreak();
    setTick((n) => n + 1);
  }, []);

  const derived = React.useMemo<StoreConnectionStatus>(() => {
    // First load → we don't yet know the truth.
    if (statusQuery.isLoading || statusQuery.isFetching) {
      // But if we've previously recorded 3+ failures for this
      // merchant, don't lie and say "loading" — keep the error
      // visible until the next successful poll.
      if (merchantId) {
        const prev = streakRef.current[merchantId];
        if (prev && prev.count >= 3) return "authtoken_error";
      }
      return "loading";
    }

    if (statusQuery.isError) {
      const err = statusQuery.error;
      const status =
        err && typeof err === "object" && "status" in err
          ? (err as { status?: number }).status
          : undefined;
      // 401/403 = token is dead. Anything else = transient — don't
      // count it toward the streak so flaky networks don't lie.
      if (status === 401 || status === 403) {
        if (!merchantId) return "authtoken_error";
        const map = { ...streakRef.current };
        const prev = map[merchantId] ?? { count: 0, firstAt: Date.now() };
        map[merchantId] = {
          count: prev.count + 1,
          firstAt: prev.firstAt ?? Date.now(),
        };
        streakRef.current = map;
        saveFailStreak(map);
        return prev.count + 1 >= 3 ? "authtoken_error" : "loading";
      }
      // Non-auth errors: still bump the streak so a sustained outage
      // eventually surfaces the error too, but with a higher
      // threshold (5) since it's more often transient.
      if (!merchantId) return "loading";
      const map = { ...streakRef.current };
      const prev = map[merchantId] ?? { count: 0, firstAt: Date.now() };
      map[merchantId] = {
        count: prev.count + 1,
        firstAt: prev.firstAt ?? Date.now(),
      };
      streakRef.current = map;
      saveFailStreak(map);
      return prev.count + 1 >= 5 ? "authtoken_error" : "loading";
    }

    if (statusQuery.data?.ok && statusQuery.data.status) {
      // Successful poll: clear the streak for this merchant. We
      // don't want a single recovered request to suddenly say
      // "Lỗi AuthToken" anymore.
      if (merchantId && streakRef.current[merchantId]) {
        const map = { ...streakRef.current };
        delete map[merchantId];
        streakRef.current = map;
        saveFailStreak(map);
      }
      return statusQuery.data.status === "ACTIVE" || statusQuery.data.status === "active"
        ? "active"
        : "loading";
    }

    return "loading";
    // We intentionally do NOT depend on tick here — streak updates
    // go through `streakRef.current` which React doesn't track. The
    // hook's external caller re-renders when the underlying query
    // changes, which is what we want.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    merchantId,
    statusQuery.isLoading,
    statusQuery.isFetching,
    statusQuery.isError,
    statusQuery.error,
    statusQuery.data?.ok,
    statusQuery.data?.status,
  ]);

  // Don't claim "active" just because the user is logged out.
  if (!merchantId) return { status: "loading", merchantId: null };

  return { status: derived, merchantId };
}

/**
 * Clears the auth-token failure streak for the given merchant (or all
 * merchants when called with no args). Useful after a successful
 * refresh-token action.
 */
export function clearAuthTokenFailStreak(merchantId?: string) {
  if (typeof window === "undefined") return;
  const map = loadFailStreak();
  if (!merchantId) {
    saveFailStreak({});
    return;
  }
  delete map[merchantId];
  saveFailStreak(map);
}
