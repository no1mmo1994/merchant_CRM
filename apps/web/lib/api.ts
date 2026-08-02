/**
 * Tiny typed fetch wrapper. All PulseOrder API calls should go through
 * this so credentials + base URL stay consistent.
 *
 * - Always sends cookies (`credentials: "include"`) so the FastAPI
 *   session cookie works in both local mode and deploy mode.
 * - Throws `ApiError` on non-2xx with the server's parsed JSON body,
 *   so TanStack Query's `error` is a useful object, not `[object]`.
 * - Reads `NEXT_PUBLIC_API_URL` at call time, not at import time, so
 *   test runs that mutate the env mid-flight behave.
 */

const BASE_URL_FALLBACK = "http://127.0.0.1:8124";

/**
 * Returns the base URL for API calls.
 *
 * In dev: Next.js's `rewrites` rule proxies `/api/*` to the FastAPI
 * server, so the browser hits its own origin (`http://localhost:3001`)
 * and we get a same-origin request — no CORS preflight, no cookie
 * domain mismatch. We detect this by checking for the dev `NODE_ENV`
 * and return an empty string (relative URLs).
 *
 * In production: there is no rewrite rule, so the frontend talks to
 * `NEXT_PUBLIC_API_URL` directly. Set that env var at build time.
 *
 * Kept as a runtime read (not module-level) so test harnesses can
 * mutate the env mid-flight.
 */
function baseUrl(): string {
  if (process.env.NODE_ENV !== "production") {
    // Dev: rely on the Next.js rewrite. Relative URLs are safer than
    // hard-coding `http://localhost:3001` — Next 16 sometimes picks a
    // different port if 3000 is occupied.
    return "";
  }
  return process.env.NEXT_PUBLIC_API_URL || BASE_URL_FALLBACK;
}

export class ApiError extends Error {
  status: number;
  body: unknown;
  constructor(status: number, message: string, body: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

interface RequestInitJson extends Omit<RequestInit, "body"> {
  json?: unknown;
}

async function request<T = unknown>(
  path: string,
  init: RequestInitJson = {}
): Promise<T> {
  const { json, headers, ...rest } = init;
  const url = path.startsWith("http")
    ? path
    : `${baseUrl()}${path.startsWith("/") ? path : `/${path}`}`;

  const res = await fetch(url, {
    ...rest,
    credentials: "include",
    headers: {
      "content-type": "application/json",
      ...(headers ?? {}),
    },
    body: json !== undefined ? JSON.stringify(json) : (rest as RequestInit).body,
  });

  const text = await res.text();
  let parsed: unknown = text;
  if (text && res.headers.get("content-type")?.includes("application/json")) {
    try {
      parsed = JSON.parse(text);
    } catch {
      /* keep as text */
    }
  }

  if (!res.ok) {
    const message = extractErrorMessage(parsed, text) || `HTTP ${res.status}`;
    throw new ApiError(res.status, message, parsed);
  }
  return parsed as T;
}

/**
 * Best-effort human-readable summary of an error response body.
 *
 * FastAPI can return `detail` in several shapes:
 *   - `string`                              → use verbatim
 *   - `{ code, message, hint?, ... }`       → prefer `message`, else `code`
 *   - `[{ type, loc, msg, ... }, ...]`      → join each `.msg` (422 validation)
 *   - anything else (object/array)          → fall through to status text
 *
 * NEVER use `String(detail)` directly — that turns every object into the
 * unreadable `"[object Object]"`, which is what users were seeing in
 * toast notifications before this helper existed.
 */
function extractErrorMessage(parsed: unknown, rawText: string): string {
  if (parsed && typeof parsed === "object" && "detail" in parsed) {
    const detail = (parsed as { detail: unknown }).detail;
    if (typeof detail === "string" && detail.trim()) {
      return detail.trim();
    }
    if (detail && typeof detail === "object" && !Array.isArray(detail)) {
      const d = detail as Record<string, unknown>;
      // PulseOrder's structured error envelope (see _login_error_to_http).
      if (typeof d.message === "string" && d.message) return d.message;
      if (typeof d.code === "string" && d.code) {
        return humanizeErrorCode(d.code);
      }
      // Generic FastAPI HTTPException({...}).
      if (typeof d.error === "string" && d.error) return d.error;
    }
    if (Array.isArray(detail)) {
      // FastAPI RequestValidationError → list of error objects with `.msg`.
      const parts = detail
        .map((item) => {
          if (item && typeof item === "object") {
            const loc = (item as { loc?: unknown }).loc;
            const msg = (item as { msg?: unknown }).msg;
            const locStr = Array.isArray(loc) && loc.length > 1
              ? loc.slice(1).join(".")
              : null;
            if (typeof msg === "string" && msg) {
              return locStr ? `${locStr}: ${msg}` : msg;
            }
          }
          return null;
        })
        .filter((s): s is string => !!s);
      if (parts.length) return parts.join("; ");
    }
  }
  // Fall back to raw text if it's not empty and looks like a real string
  // (not the raw JSON we already failed to extract from).
  const trimmed = rawText.trim();
  if (trimmed && !trimmed.startsWith("{") && !trimmed.startsWith("[")) {
    return trimmed;
  }
  return "";
}

/**
 * Friendly fallback label when the backend returned a `code` we recognise
 * but no human `message`. Keeps the user informed even if the backend
 * forgot to populate `message`.
 */
function humanizeErrorCode(code: string): string {
  return code
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export const api = {
  get: <T = unknown>(path: string, init?: RequestInitJson) =>
    request<T>(path, { ...init, method: "GET" }),
  post: <T = unknown>(path: string, json?: unknown, init?: RequestInitJson) =>
    request<T>(path, { ...init, method: "POST", json }),
  put: <T = unknown>(path: string, json?: unknown, init?: RequestInitJson) =>
    request<T>(path, { ...init, method: "PUT", json }),
  patch: <T = unknown>(path: string, json?: unknown, init?: RequestInitJson) =>
    request<T>(path, { ...init, method: "PATCH", json }),
  delete: <T = unknown>(path: string, init?: RequestInitJson) =>
    request<T>(path, { ...init, method: "DELETE" }),
};
