"use client";

import { QueryClient } from "@tanstack/react-query";

/**
 * PulseOrder QueryClient defaults.
 *
 * - 30s stale time so charts + store lists don't refetch on every
 *   focus, but still feel live.
 * - `refetchOnWindowFocus: false` — single owner, no concurrent
 *   edits; manual refresh is fine.
 * - Single retry on network errors (5xx), no retry on 4xx.
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        gcTime: 5 * 60_000,
        refetchOnWindowFocus: false,
        retry: (failureCount, error: unknown) => {
          if (
            error &&
            typeof error === "object" &&
            "status" in error &&
            typeof (error as { status: unknown }).status === "number"
          ) {
            const status = (error as { status: number }).status;
            if (status >= 400 && status < 500) return false;
          }
          return failureCount < 1;
        },
      },
      mutations: {
        retry: false,
      },
    },
  });
}
