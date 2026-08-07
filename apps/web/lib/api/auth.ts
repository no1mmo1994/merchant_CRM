import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";

/**
 * Auth API surface. All requests use `credentials: "include"` (already set
 * in the shared `api` client) so the backend's httponly session cookie
 * travels with the request.
 */

export interface LoginInput {
  email: string;
  password: string;
  /**
   * x-ray token captured from a recent Grab Merchant app / browser
   * DevTools POST to `/grabid/v1/authnv4/login`. The HMAC tag inside
   * is bound to the device clock and goes stale in a few hours, so
   * the user pastes a fresh one each sign-in. The backend feeds the
   * same token into step-1 and step-3 of the 3-step login.
   */
  xray_token: string;
}

export interface AuthUser {
  id: number;
  username: string;
  created_at: string;
}

export interface AuthStore {
  id: number;
  merchant_id: string;
  name: string;
  address: string;
  last_refresh_at: string | null;
  created_at: string;
}

export interface LoginResponse {
  user: AuthUser;
  store: AuthStore;
  message: string;
}

export interface MeResponse {
  user: AuthUser;
  stores: AuthStore[];
}

/**
 * Structured error envelope the backend returns for every Grab-related
 * login failure. `code` is the stable identifier the frontend matches
 * on; `message` is already human-friendly; `hint` is next-step guidance;
 * `fields` tells the form which input to re-focus.
 */
export interface LoginErrorDetail {
  code:
    | "grab_rate_limited"
    | "grab_clock_drift"
    | "grab_xray_rejected"
    | "invalid_email"
    | "wrong_password"
    | "grab_upstream_error"
    | "grab_login_failed";
  message: string;
  hint?: string;
  fields?: string[];
  source?: "login" | "refresh-token";
  request_id?: string | null;
  /**
   * Hours since the JWT `iat` claim. Positive = token is stale;
   * negative = token's iat is in the future (device clock ahead).
   * `null` when the token wasn't a JWT we could decode. Present on
   * `grab_clock_drift` and `grab_rate_limited` (the latter so the
   * LoginForm can warn when the bundled token is older than ~4h and
   * recommend re-capture rather than just waiting out the throttle).
   */
  xray_age_hours?: number | null;
  /**
   * Approximate seconds until Grab's per-(x-ray+IP) throttle window
   * is likely clear. Frontend uses this for an auto-retry countdown
   * on `grab_rate_limited`. Backend returns ~300 (5 minutes) by
   * default; absent on other error codes.
   */
  retry_after_seconds?: number;
  /**
   * Grab's own classifier string, normalised by the backend (e.g.
   * "invalid verify challenge payload"). Narrow and pre-classified —
   * never the raw upstream body, which the backend deliberately
   * withholds. Present on `grab_rate_limited` and `wrong_password` so
   * triage can tell a rejected password apart from an expired challenge
   * session without reading server logs.
   */
  grab_reason?: string | null;
}

/**
 * Pull the structured `detail.code` envelope out of an `ApiError`.
 * Returns `null` when the error isn't a structured login error (e.g.
 * a network failure or a 404 from a different endpoint).
 */
function readLoginErrorDetail(err: unknown): LoginErrorDetail | null {
  if (!(err instanceof ApiError)) return null;
  const body = err.body as { detail?: unknown } | undefined;
  if (!body || typeof body !== "object") return null;
  const detail = body.detail;
  if (!detail || typeof detail !== "object") return null;
  const d = detail as Record<string, unknown>;
  if (typeof d.code !== "string") return null;
  return d as unknown as LoginErrorDetail;
}

const ME_KEY = ["auth", "me"] as const;

async function login(input: LoginInput): Promise<LoginResponse> {
  return api.post<LoginResponse>("/api/auth/login", input);
}

async function logout(): Promise<{ ok: true }> {
  return api.post<{ ok: true }>("/api/auth/logout");
}

/**
 * Wrap a one-shot promise with a timeout watchdog. The Next.js dev
 * proxy occasionally emits "socket hang up" mid-request, leaving
 * TanStack Query in `isPending=true` indefinitely. Rejecting after a
 * bounded wait gives the UI a structured error to surface so the
 * "loading" affordance isn't permanent.
 */
function withTimeout<T>(p: Promise<T>, label: string, ms = 12_000): Promise<T> {
  return Promise.race<T>([
    p,
    new Promise<T>((_resolve, reject) => {
      window.setTimeout(
        () => reject(new ApiError(0, `${label} timed out after ${ms / 1000}s.`, null)),
        ms,
      );
    }),
  ]);
}

async function fetchMe(): Promise<MeResponse> {
  return withTimeout(api.get<MeResponse>("/api/auth/me"), "/api/auth/me", 12_000);
}

/**
 * True when the error indicates Grab rejected the *bundled* x-ray token
 * (signature invalid, clock-drifted, replayed, …) or is throttling the
 * network. Kept so server-side / monitoring code can still branch on it,
 * but no longer used by the LoginForm to focus a form field — the user
 * no longer enters an x-ray.
 */
export function isXrayExpiredError(err: unknown): boolean {
  const detail = readLoginErrorDetail(err);
  if (!detail) return false;
  return (
    detail.code === "grab_clock_drift" ||
    detail.code === "grab_xray_rejected" ||
    detail.code === "grab_rate_limited"
  );
}

export function getLoginErrorDetail(err: unknown): LoginErrorDetail | null {
  return readLoginErrorDetail(err);
}

export function useLogin() {
  const qc = useQueryClient();
  return useMutation({
    // Race the request against a watchdog so a hung Next.js dev
    // proxy ("socket hang up") can't leave the form's submit button
    // spinning forever. Surfaces as a structured ApiError so the
    // existing error toast / banner code path renders a useful
    // "request timed out" hint instead of a quiet freeze.
    //
    // 45s covers one full Grab step-1 roundtrip from a throttled
    // endpoint (Grab can take 5-15s to respond when 429-throttling a
    // x-ray + IP pair) plus a healthy margin for the dev proxy.
    // Backend is now fail-fast on its own retry loop
    // (services/api/grab/auth.py removed its 3-attempt backoff), so
    // when Grab returns a 429 the user sees the structured
    // `grab_rate_limited` LoginErrorDetail — not this watchdog.
    mutationFn: (input: LoginInput) =>
      Promise.race<LoginResponse>([
        login(input),
        new Promise<LoginResponse>((_resolve, reject) => {
          window.setTimeout(
            () => reject(new ApiError(0, "Login request timed out (no response after 45s). The dev proxy may be stalled — try again.", null)),
            45_000,
          );
        }),
      ]),
    onSuccess: (data) => {
      qc.setQueryData(ME_KEY, { user: data.user, stores: [data.store] });
      qc.invalidateQueries({ queryKey: ["stores"] });
    },
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: logout,
    onSuccess: () => {
      qc.setQueryData(ME_KEY, null);
      qc.clear();
    },
  });
}

export function useMe() {
  return useQuery({
    queryKey: ME_KEY,
    queryFn: fetchMe,
    retry: (failureCount, error) => {
      // 401 means "not logged in" — don't retry, just report.
      if (error instanceof ApiError && error.status === 401) return false;
      return failureCount < 1;
    },
    staleTime: 60_000,
  });
}

export { ME_KEY };
