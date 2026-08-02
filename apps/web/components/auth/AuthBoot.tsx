"use client";

import * as React from "react";
import { useAuthStore } from "@/lib/stores/auth-store";
import { useMe } from "@/lib/api/auth";

/**
 * Renders nothing. Mounted once in <Providers>. On app boot it issues
 * `/api/auth/me` and:
 * - Hydrates the Zustand auth store on success
 * - Clears the store on 401 (the session cookie is gone)
 *
 * Centralizing this here means every page (dashboard, login, landing)
 * benefits from a single, cached `useMe` request — TanStack Query
 * deduplicates by queryKey.
 */
export function AuthBoot() {
  const setSession = useAuthStore((s) => s.setSession);
  const clear = useAuthStore((s) => s.clear);
  const setRef = React.useRef(setSession);
  const clearRef = React.useRef(clear);
  setRef.current = setSession;
  clearRef.current = clear;

  const me = useMe();

  React.useEffect(() => {
    if (me.data) {
      setRef.current(me.data.user, me.data.stores);
    } else if (me.error && me.error instanceof Error) {
      const status =
        "status" in me.error && typeof (me.error as { status?: unknown }).status === "number"
          ? (me.error as { status: number }).status
          : 0;
      if (status === 401) {
        clearRef.current();
      }
    } else if (me.isError) {
      clearRef.current();
    }
  }, [me.data, me.error, me.isError]);

  return null;
}
