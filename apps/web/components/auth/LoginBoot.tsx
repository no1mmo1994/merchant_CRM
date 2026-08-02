"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/lib/stores/auth-store";
import { useMe } from "@/lib/api/auth";

/**
 * Auth gate for the /login page. If the user already has a valid
 * session, redirect them straight to the dashboard. Renders a tiny
 * skeleton while the check resolves — avoids a "flash of the login form"
 * when an authenticated user lands on `/login` via a stale link.
 *
 * `next=…` is honored so deep links survive the redirect.
 */
export function LoginBoot({
  children,
  nextPath = "/dashboard",
}: {
  children: React.ReactNode;
  nextPath?: string;
}) {
  const router = useRouter();
  const user = useAuthStore((s) => s.user);
  const me = useMe();

  const hasSession =
    !!user || (me.data && me.data.user && me.data.stores.length > 0);

  React.useEffect(() => {
    if (hasSession) router.replace(nextPath);
  }, [hasSession, nextPath, router]);

  // Loading state — `/api/auth/me` is in-flight (skipped only on 401).
  if (!me.isError && !me.data && me.isFetching) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center text-(--color-muted-foreground)">
        Checking session…
      </div>
    );
  }

  if (hasSession) return null;

  return <>{children}</>;
}
