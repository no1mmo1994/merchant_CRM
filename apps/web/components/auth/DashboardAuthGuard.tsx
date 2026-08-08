"use client";

import * as React from "react";
import { useRouter, usePathname } from "next/navigation";
import { useAuthStore } from "@/lib/stores/auth-store";
import { useMe } from "@/lib/api/auth";
import { Loader2 } from "lucide-react";

/**
 * Auth guard for any `app/(dashboard)/**` page. Mounted once in
 * `<DashboardLayout>`, it:
 *
 * 1. Detects when the user is logged out (Zustand cleared or
 *    /api/auth/me returns 401).
 * 2. Performs a FULL-HARD redirect to `/login?next=<currentPath>` and
 *    reloads the entire app (we used `router.push()` + `refresh()`
 *    before, which kept the dashboard tree in memory, allowing the
 *    user to keep clicking sidebar items in a logged-out state).
 * 3. Renders a static loading overlay while redirecting so the user
 *    can't fire any further clicks (replaces the
 *    "still-clickable-after-logout" UI from the bug report).
 *
 * The full-page navigation (vs `router.push`) is what makes this
 * safe: we discard the React tree entirely, which is the only way to
 * guarantee the `(dashboard)` layout doesn't keep accepting input.
 */
export function DashboardAuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const user = useAuthStore((s) => s.user);
  const clear = useAuthStore((s) => s.clear);
  const me = useMe();

  const hasLocalSession = !!user;
  const meIsAuthed = !!me.data?.user;
  // If `me` is in its loading window (first /api/auth/me in flight)
  // we keep rendering the children so the dashboard doesn't flash —
  // but only if the local Zustand store already shows a user. If
  // both are empty we redirect immediately.
  const status = me.isError
    ? "unauthenticated"
    : me.data
      ? "authenticated"
      : "loading";

  const redirectedRef = React.useRef(false);
  // Fallback when the request never settles — Next.js dev proxy can
  // hang ("socket hang up") and leave us stuck on the loading overlay.
  // After 8s we force a redirect to /login so the user isn't frozen.
  const [loadingTimedOut, setLoadingTimedOut] = React.useState(false);
  React.useEffect(() => {
    if (!hasLocalSession && me.isFetching) {
      const t = window.setTimeout(() => setLoadingTimedOut(true), 8000);
      return () => window.clearTimeout(t);
    }
    setLoadingTimedOut(false);
    return undefined;
  }, [hasLocalSession, me.isFetching]);

  React.useEffect(() => {
    if (redirectedRef.current) return;
    // 0) Loading guard timed out — proxy hangup, browser offline, etc.
    //    Force a hard redirect instead of leaving the user staring at
    //    the spinner forever.
    if (loadingTimedOut && !hasLocalSession) {
      redirectedRef.current = true;
      hardRedirectToLogin(router, pathname);
      return;
    }
    // 1) /api/auth/me returned 401 → backend says we're out.
    if (me.isError) {
      const status =
        "status" in me.error && typeof (me.error as { status?: unknown }).status === "number"
          ? (me.error as { status: number }).status
          : 0;
      if (status === 401 || status === 403) {
        clear();
        redirectedRef.current = true;
        hardRedirectToLogin(router, pathname);
        return;
      }
    }
    // 2) /api/auth/me succeeded but the user is missing.
    if (me.data && !me.data.user) {
      clear();
      redirectedRef.current = true;
      hardRedirectToLogin(router, pathname);
      return;
    }
    // 3) /api/auth/me hasn't loaded yet AND local store is also empty
    //    (e.g. after a hard reload or right after logout). We only
    //    redirect once the query has settled — otherwise we'd loop
    //    every time the page is opened fresh.
    if (!me.isFetching && !me.data && !hasLocalSession) {
      redirectedRef.current = true;
      hardRedirectToLogin(router, pathname);
      return;
    }
  }, [
    me.data,
    me.error,
    me.isError,
    me.isFetching,
    hasLocalSession,
    clear,
    router,
    pathname,
    loadingTimedOut,
  ]);

  // While the very first /api/auth/me is in flight, render a static
  // overlay so the user can't poke anything until we know whether
  // they're authenticated. After the 8s timeout (see effect above)
  // we swap to the LockedScreen so a hung proxy doesn't trap the user.
  if (status === "loading" && !hasLocalSession && !loadingTimedOut) {
    return (
      <div
        className="flex min-h-[60vh] items-center justify-center gap-2 text-sm text-(--color-muted-foreground)"
        data-testid="auth-guard-loading"
      >
        <Loader2 className="h-4 w-4 animate-spin" />
        Đang xác thực phiên đăng nhập…
      </div>
    );
  }

  // If `/api/auth/me` returned no user but local cache still has one,
  // we render a *non-interactive* pending screen — disabled sidebar,
  // disabled topbar — until the redirect kicks in. The (dashboard)
  // layout already redirects via the effect above, so this path
  // mostly matters for the few ms before window.location changes.
  if (!meIsAuthed && !hasLocalSession) {
    return <LockedScreen />;
  }

  return <>{children}</>;
}

function LockedScreen() {
  return (
    <div
      role="alert"
      data-testid="auth-guard-locked"
      className="flex min-h-[60vh] flex-col items-center justify-center gap-3 p-6 text-center"
    >
      <div className="rounded-full bg-amber-500/10 p-3 text-amber-600 dark:text-amber-400">
        <Loader2 className="h-6 w-6 animate-spin" />
      </div>
      <h2 className="text-lg font-semibold text-(--color-foreground)">
        Phiên đăng nhập đã kết thúc
      </h2>
      <p className="max-w-sm text-sm text-(--color-muted-foreground)">
        Đang chuyển hướng bạn về trang đăng nhập. Nếu trình duyệt không tự chuyển, vui lòng nhấn nút bên dưới.
      </p>
      <button
        type="button"
        className="mt-2 rounded-md bg-(--color-brand) px-4 py-2 text-sm font-medium text-white hover:bg-(--color-brand-hover)"
        onClick={() => {
          if (typeof window !== "undefined") {
            window.location.href = "/login";
          }
        }}
      >
        Về trang đăng nhập
      </button>
    </div>
  );
}

/**
 * Hard navigation to /login. We use window.location instead of
 * next/navigation because:
 *   - The `(dashboard)` layout persists across `router.push()` calls
 *     if they're between dashboard sub-pages, and we need to unmount
 *     the WHOLE tree so background data fetches don't keep firing.
 *   - router.refresh() re-evaluates server components but doesn't
 *     evict the React client tree — so the user reported that the
 *     sidebar was still clickable after logout.
 * A full window.location.assign() guarantees a clean slate.
 */
function hardRedirectToLogin(
  _router: ReturnType<typeof useRouter>,
  _pathname: string | null,
) {
  if (typeof window === "undefined") return;
  // Read straight from `window.location` so the query string comes along
  // — `usePathname()` drops it, which sent a merchant whose session
  // expired on `/menu?tab=addons` back to the items tab after re-login.
  const here = window.location.pathname + window.location.search;
  const next = here && here !== "/" ? `?next=${encodeURIComponent(here)}` : "";
  window.location.assign(`/login${next}`);
}
