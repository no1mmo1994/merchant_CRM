import { NextResponse, type NextRequest } from "next/server";

/**
 * Auth wall. Runs in the Next.js edge runtime before a route is
 * rendered.
 *
 * PulseOrder uses an httponly, server-set session cookie called
 * `pulseorder_session` (see services/api/app/core/security.py). Its
 * presence on a request is a necessary (not sufficient) signal of
 * authentication — middleware can't decrypt it, so the page-level
 * AuthBoot still re-validates via `/api/auth/me`.
 *
 * Two rules:
 * 1. Visiting `/login` (or `/auth/*`) while signed in → redirect to
 *    `/dashboard` (or `?next`).
 * 2. Visiting any other route while signed out → redirect to
 *    `/login?next=…`.
 *
 * Public routes (no auth required): `/`, `/api/*` (proxied via the
 * FastAPI server, not Next.js).
 */

const SESSION_COOKIE = "pulseorder_session";

const PUBLIC_PREFIXES = ["/login"];

function hasSession(req: NextRequest): boolean {
  return Boolean(req.cookies.get(SESSION_COOKIE)?.value);
}

export function proxy(req: NextRequest) {
  const { pathname, search } = req.nextUrl;
  const sessioned = hasSession(req);

  // Root: bounce based on session.  Signed-in → /dashboard, signed-out →
  // /login.  The (marketing)/page.tsx Phase 04 shell is intentionally
  // unreachable from the app; we don't want a public landing anymore.
  if (pathname === "/") {
    const url = req.nextUrl.clone();
    url.pathname = sessioned ? "/dashboard" : "/login";
    url.search = "";
    return NextResponse.redirect(url);
  }

  // Auth surface: signed-in users shouldn't see the form.
  if (PUBLIC_PREFIXES.some((p) => pathname === p || pathname.startsWith(`${p}/`))) {
    if (sessioned) {
      const url = req.nextUrl.clone();
      url.pathname = "/dashboard";
      url.search = "";
      return NextResponse.redirect(url);
    }
    return NextResponse.next();
  }

  // Everything else (dashboard/menu/...) requires the cookie.
  if (!sessioned) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.search = `?next=${encodeURIComponent(pathname + search)}`;
    return NextResponse.redirect(url);
  }

  return NextResponse.next();
}

/**
 * Skip middleware for:
 *  - Next.js internals (`_next/*`)
 *  - Static assets (`favicon.ico`, anything with a `.` extension)
 *  - `/api/*` — these are rewritten to the FastAPI bridge (see
 *    `next.config.ts` → `rewrites()`). The proxy must NOT touch them,
 *    otherwise unauthenticated callers of `/api/auth/login` get bounced
 *    to `/login?next=…` before the rewrite can hand the request to
 *    FastAPI. Auth on the API side is enforced by the FastAPI session
 *    middleware + `requires_auth()` dependency, not by this proxy.
 */
export const config = {
  matcher: ["/((?!_next/|api/|.*\\..*).*)"],
};