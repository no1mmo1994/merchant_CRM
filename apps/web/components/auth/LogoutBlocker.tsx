"use client";

import * as React from "react";
import { Loader2 } from "lucide-react";
import { useMe } from "@/lib/api/auth";

/**
 * Non-dismissible overlay shown while we're either:
 *   - in the middle of logging out (fetching /api/auth/logout)
 *
 * `useMe` returning 401 is treated as "session ended, redirecting"
 * — but the redirect is a full window.location navigation; until it
 * actually lands, this overlay prevents the user from clicking
 * sidebar / menu items (the bug was: after clicking Logout, the
 * sidebar stayed interactive for ~1s before the redirect hit).
 *
 * We deliberately listen to BOTH the auth store's user field and
 * the useMe query state — any moment either says "unauthenticated",
 * the overlay shows + input is locked.
 */
export function LogoutBlocker({ children }: { children: React.ReactNode }) {
  const me = useMe();
  const [forceLock, setForceLock] = React.useState(false);

  // When we lose the /api/auth/me query (because the redirect navigation
  // hasn't completed yet), surface the locked overlay one more frame.
  const isUnauthenticated = !!me.isError || (!!me.data && !me.data.user);

  React.useEffect(() => {
    if (isUnauthenticated) {
      setForceLock(true);
      // Once the redirect has run we'll unmount; bail if not.
      const t = window.setTimeout(() => setForceLock(false), 4_000);
      return () => window.clearTimeout(t);
    }
    return undefined;
  }, [isUnauthenticated]);

  const showLock = isUnauthenticated || forceLock;

  return (
    <>
      {children}
      {showLock && (
        <div
          role="alertdialog"
          aria-live="assertive"
          aria-label="Đang chuyển hướng về trang đăng nhập"
          data-testid="logout-blocker"
          className="fixed inset-0 z-[200] flex items-center justify-center bg-black/60 backdrop-blur-sm"
        >
          <div className="flex max-w-sm flex-col items-center gap-3 rounded-xl border border-(--color-border) bg-(--color-surface) p-6 text-center shadow-2xl">
            <Loader2 className="h-8 w-8 animate-spin text-(--color-brand)" />
            <h2 className="text-base font-semibold text-(--color-foreground)">
              Đang đăng xuất…
            </h2>
            <p className="text-sm text-(--color-muted-foreground)">
              Vui lòng đợi trong giây lát, bạn sẽ được chuyển về trang đăng nhập.
            </p>
          </div>
        </div>
      )}
    </>
  );
}
