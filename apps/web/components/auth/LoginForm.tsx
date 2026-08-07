"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  AlertTriangle,
  Eye,
  EyeOff,
  KeyRound,
  Loader2,
  RadioTower,
  ShieldCheck,
  Timer,
  XCircle,
} from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { BrandLogo } from "./BrandLogo";
import { useAuthStore } from "@/lib/stores/auth-store";
import { ApiError } from "@/lib/api";
import {
  getLoginErrorDetail,
  useLogin,
} from "@/lib/api/auth";

/**
 * 3-field login form. The backend's `LoginRequest` requires:
 *   email, password, xray_token
 *
 * The x-ray token is captured once per sign-in from the user's
 * Grab Merchant app (or browser DevTools). It's HMAC-tagged against
 * the device clock and goes stale in a few hours — that's why we
 * never reuse a stored one. The backend feeds the same token into
 * step-1 and step-3 of the 3-step login (matching `Login/login1-done.py`).
 *
 * After login the backend calls Grab's
 * `GET /mex-app/troy/user-profile/v2/details` and derives both the
 * merchant id (`user_profile.merchant_grab_id`) and the store display
 * name (`user_profile_details.first_name`) — so the user no longer
 * has to type a store name at all.
 */
const schema = z.object({
  email: z.string().email("Looks like that email isn't valid."),
  password: z.string().min(6, "Grab password is at least 6 characters."),
  xray_token: z.string().min(10, "Paste the x-ray token from your Grab app or DevTools."),
});

type FormValues = z.infer<typeof schema>;

export function LoginForm() {
  const router = useRouter();
  const search = useSearchParams();
  const nextPath = search.get("next") ?? "/dashboard";

  const setSession = useAuthStore((s) => s.setSession);
  const login = useLogin();

  const [showPassword, setShowPassword] = React.useState(false);
  const [showXray, setShowXray] = React.useState(false);
  /**
   * Last structured LoginErrorDetail we surfaced. Held in state (not just
   * toasted) so the hint — "wait 10 min then retry", "check the email" —
   * stays visible while the user actually goes to do the action. Cleared
   * on the next submit attempt.
   */
  const [lastError, setLastError] = React.useState<{
    detail: import("@/lib/api/auth").LoginErrorDetail;
    focusField?: keyof FormValues;
  } | null>(null);

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      email: "",
      password: "",
      xray_token: "",
    },
    mode: "onBlur",
  });

  /**
   * Synchronous re-entrancy guard. The button's `disabled` attribute only
   * takes effect after React commits the next render, so a fast double-click
   * or rapid Enter presses can fire several submit events before the
   * `isPending` state flips. A ref updates immediately on entry, blocking
   * all subsequent in-flight submissions until the current one resolves.
   */
  const submittingRef = React.useRef(false);

  const onSubmit = form.handleSubmit(async (values) => {
    if (submittingRef.current) return; // ignore re-entrant submit
    submittingRef.current = true;
    // Clear any pinned prior error before retrying — a stale banner would
    // mislabel a fresh failure.
    setLastError(null);
    try {
      const data = await login.mutateAsync(values);
      setSession(data.user, [data.store]);
      toast.success(`Welcome, ${data.user.username}`);
      router.push(nextPath);
    } catch (err) {
      const detail = getLoginErrorDetail(err);
      // Structured error from the backend: surface `message` (already
      // human-friendly) + `hint` (next-step guidance) as a single toast.
      if (detail) {
        const body = detail.hint
          ? `${detail.message} — ${detail.hint}`
          : detail.message;
        toast.error(body, { duration: 7000 });
        // Focus the first field the backend says is wrong.
        const requestedField = detail.fields?.[0];
        const focusField = (["email", "password", "xray_token"] as const).find(
          (k) => k === requestedField,
        );
        if (focusField) {
          form.setFocus(focusField);
        }
        setLastError({ detail, focusField });
        return;
      }
      // Fallback path: non-structured error. `err.message` could itself be
      // the unhelpful `"[object Object]"` if the underlying `api.ts`
      // extractor failed (defence in depth — see api.ts:extractErrorMessage).
      const fallbackMessage =
        err instanceof ApiError && err.message && err.message !== "[object Object]"
          ? err.message
          : err instanceof ApiError && err.status === 401
            ? "Grab rejected those credentials."
            : err instanceof ApiError
              ? `Request failed (HTTP ${err.status}).`
              : "Unexpected error. Please retry.";
      toast.error(fallbackMessage);
    } finally {
      submittingRef.current = false;
    }
  });

  const submitting = login.isPending;

  return (
    <Card className="w-full max-w-md border-(--color-border) shadow-lg">
      <CardHeader className="space-y-2">
        <div className="flex items-center justify-between">
          <BrandLogo size={28} className="lg:hidden" />
          <span className="rounded-full bg-(--color-surface-2) px-2 py-1 text-xs text-(--color-muted-foreground)">
            Bước 1 / 1
          </span>
        </div>
        <CardTitle className="text-2xl">Kết nối cửa hàng đầu tiên</CardTitle>
        <CardDescription>
          Nhập email, mật khẩu Grab Merchant và token x-ray từ lần đăng nhập gần nhất.
          PulseOrder sử dụng chúng để đăng nhập một lần qua api.grab.com. Merchant ID
          và tên cửa hàng được tự động phát hiện từ Grab sau khi đăng nhập.
        </CardDescription>
      </CardHeader>

      <CardContent>
        <form onSubmit={onSubmit} className="space-y-4" noValidate>
          <Field
            id="email"
            label="Email"
            type="email"
            autoComplete="email"
            placeholder="owner@yourbrand.com"
            error={form.formState.errors.email?.message}
            registration={form.register("email")}
            disabled={submitting}
          />

          <Field
            id="password"
            label="Mật khẩu Grab"
            type={showPassword ? "text" : "password"}
            autoComplete="current-password"
            placeholder="••••••••"
            error={form.formState.errors.password?.message}
            registration={form.register("password")}
            disabled={submitting}
            trailing={
              <button
                type="button"
                onClick={() => setShowPassword((s) => !s)}
                className="text-(--color-muted-foreground) hover:text-(--color-foreground)"
                aria-label={showPassword ? "Ẩn mật khẩu" : "Hiện mật khẩu"}
              >
                {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            }
          />

          <XrayField
            error={form.formState.errors.xray_token?.message}
            registration={form.register("xray_token")}
            disabled={submitting}
            visible={showXray}
            onToggleVisibility={() => setShowXray((s) => !s)}
          />

          {lastError && (
            <LoginErrorBanner
              detail={lastError.detail}
              onDismiss={() => setLastError(null)}
              onAutoRetry={() => {
                // Banner's countdown fired — clear pinned error and
                // resubmit. Falls through to `setLastError(null)` and the
                // normal submit handler so the error banner can surface
                // a fresh failure if Grab is still throttling.
                setLastError(null);
                void onSubmit();
              }}
            />
          )}

          <Button
            type="submit"
            size="lg"
            disabled={submitting}
            className="w-full"
          >
            {submitting ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Đang xác thực với Grab…
              </>
            ) : (
              <>
                <ShieldCheck className="h-4 w-4" />
                Đăng nhập PulseOrder
              </>
            )}
          </Button>

          <p className="flex items-center justify-center gap-1.5 text-xs text-(--color-muted-foreground)">
            <KeyRound className="h-3 w-3" />
            Token được mã hóa Fernet khi lưu trữ. Không gửi đến bên thứ ba.
          </p>
        </form>
      </CardContent>
    </Card>
  );
}

interface FieldProps extends React.InputHTMLAttributes<HTMLInputElement> {
  id: string;
  label: string;
  error?: string;
  registration: ReturnType<ReturnType<typeof useForm<FormValues>>["register"]>;
  trailing?: React.ReactNode;
}

/**
 * Single labelled input. Pulled out so the form's fields stay readable.
 */
function Field({ id, label, error, registration, trailing, disabled, ...rest }: FieldProps) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <div className="relative">
        <Input
          id={id}
          aria-invalid={!!error}
          aria-describedby={error ? `${id}-error` : undefined}
          disabled={disabled}
          {...registration}
          {...rest}
          className="pr-10"
        />
        {trailing && (
          <div className="absolute inset-y-0 right-2 flex items-center">{trailing}</div>
        )}
      </div>
      {error && (
        <p id={`${id}-error`} className="text-xs text-(--color-destructive)">
          {error}
        </p>
      )}
    </div>
  );
}

/**
 * Multi-line x-ray token input. Mirrors the styling of `Field` (border,
 * focus ring, error color, trailing show/hide toggle) but uses a
 * `<textarea>` so the long base64 token doesn't fight a single-line
 * `Input`. Kept as a separate component instead of overloading `Field`
 * with a `multiline` prop — the trailing-icon positioning differs.
 */
function XrayField({
  error,
  registration,
  disabled,
  visible,
  onToggleVisibility,
}: {
  error?: string;
  registration: ReturnType<ReturnType<typeof useForm<FormValues>>["register"]>;
  disabled?: boolean;
  visible: boolean;
  onToggleVisibility: () => void;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor="xray_token" className="flex items-center gap-1.5">
        <RadioTower className="h-3.5 w-3.5 text-(--color-muted-foreground)" />
        x-ray Token
      </Label>
      <div className="relative">
        <textarea
          id="xray_token"
          rows={3}
          spellCheck={false}
          autoComplete="off"
          autoCorrect="off"
          autoCapitalize="off"
          aria-invalid={!!error}
          aria-describedby={error ? "xray_token-error" : "xray_token-hint"}
          disabled={disabled}
          placeholder="eyJhIjoi…paste the x-ray header from the most recent POST to /authnv4/login…"
          className="w-full resize-y rounded-lg border border-input bg-transparent px-2.5 py-1.5 font-mono text-xs leading-relaxed transition-colors outline-none placeholder:text-muted-foreground/70 focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:pointer-events-none disabled:cursor-not-allowed disabled:bg-input/50 disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/20 dark:bg-input/30 dark:disabled:bg-input/80 dark:aria-invalid:border-destructive/50 dark:aria-invalid:ring-destructive/40"
          style={
            // Native textarea can't honour `type="password"`. If the user
            // chose to hide the value we collapse to `type`-like styling via
            // `text-security` (WebKit/Safari) and a generic blur fallback.
            visible
              ? undefined
              : ({
                  WebkitTextSecurity: "disc",
                  textSecurity: "disc",
                  filter: "blur(0.18em)",
                  letterSpacing: "0.1em",
                } as React.CSSProperties)
          }
          {...registration}
        />
        <button
          type="button"
          onClick={onToggleVisibility}
          aria-label={visible ? "Ẩn x-ray token" : "Hiện x-ray token"}
          className="absolute right-2 top-2 rounded p-1 text-(--color-muted-foreground) hover:text-(--color-foreground)"
        >
          {visible ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
        </button>
      </div>
      {error ? (
        <p id="xray_token-error" className="text-xs text-(--color-destructive)">
          {error}
        </p>
      ) : (
        <p id="xray_token-hint" className="text-xs leading-relaxed text-(--color-muted-foreground)">
          Capture from Grab Merchant app network logs (or DevTools → Network → filter
          <code className="mx-1 rounded bg-(--color-surface-2) px-1 font-mono text-[10px]">authnv4</code>
          → POST <code className="font-mono text-[10px]">login</code> → <code className="font-mono text-[10px]">x-ray</code> header). The token
          expires in a few hours — paste a fresh one each sign-in.
        </p>
      )}
    </div>
  );
}

/**
 * Maps a LoginErrorDetail `code` to the visual tone (border / icon / label)
 * that best communicates what the user needs to do. Kept inline so the
 * form is the single source of truth for which colors map to which
 * error category.
 *
 * `grab_clock_drift` and `grab_xray_rejected` tell the user to recapture
 * a fresh x-ray token (their device clock has drifted, or Grab rejected
 * the HMAC) — `bannerTone` is the place where those visual categories
 * live.
 *
 * `wrong_password` and `invalid_email` are deliberately NOT in that
 * token-recapture family and carry their own labels: both come from
 * credential steps the x-ray token either never touches (step 2 sends no
 * `x-ray` header) or has already cleared (step 1). Labelling them "token"
 * is what previously sent operators off to re-capture a working token.
 * Codes with no case fall through to the generic "Đăng nhập thất bại".
 */
function bannerTone(code: import("@/lib/api/auth").LoginErrorDetail["code"]): {
  Icon: typeof AlertTriangle;
  label: string;
  className: string;
} {
  switch (code) {
    case "grab_clock_drift":
      return {
        Icon: AlertTriangle,
        label: "Token server bị lệch",
        className:
          "border-amber-500/40 bg-amber-500/10 text-amber-900 dark:text-amber-100",
      };
    case "grab_rate_limited":
      return {
        Icon: AlertTriangle,
        label: "Bị giới hạn tần suất",
        className:
          "border-orange-500/40 bg-orange-500/10 text-orange-900 dark:text-orange-100",
      };
    case "grab_xray_rejected":
      return {
        Icon: XCircle,
        label: "Token server bị từ chối",
        className:
          "border-red-500/40 bg-red-500/10 text-red-900 dark:text-red-100",
      };
    // Credential errors get their own labels so the banner never says
    // "token" for a failure the token had no part in — step 2 (password)
    // carries no x-ray header, and step 1 (email) already passed it.
    case "wrong_password":
      return {
        Icon: XCircle,
        label: "Sai mật khẩu Grab",
        className:
          "border-red-500/40 bg-red-500/10 text-red-900 dark:text-red-100",
      };
    case "invalid_email":
      return {
        Icon: XCircle,
        label: "Email không đúng",
        className:
          "border-red-500/40 bg-red-500/10 text-red-900 dark:text-red-100",
      };
    default:
      return {
        Icon: AlertTriangle,
        label: "Đăng nhập thất bại",
        className:
          "border-destructive/40 bg-destructive/10 text-destructive",
      };
  }
}

/**
 * Persistent inline error banner. Renders above the submit button so the
 * `hint` (e.g. "wait 5 minutes then retry", "double-check the email")
 * stays visible while the user actually goes to perform the action —
 * unlike a toast that vanishes after a few seconds.
 *
 * `grab_rate_limited` is special: the backend already burned 2 retries
 * with exponential backoff, so by the time the user sees the banner
 * we're confident Grab is in its ~5 min throttle window. We render a
 * live countdown that fires `onAutoRetry` when it elapses — one more
 * attempt without forcing the user to come back to the tab.
 */
function LoginErrorBanner({
  detail,
  onDismiss,
  onAutoRetry,
}: {
  detail: import("@/lib/api/auth").LoginErrorDetail;
  onDismiss: () => void;
  onAutoRetry?: () => void;
}) {
  const { Icon, label, className } = bannerTone(detail.code);
  const ageH = detail.xray_age_hours;
  // Stale-token warning: only fires when the JWT iat is older than ~4h,
  // meaning the HMAC tag won't survive a 5-min throttle window. A future
  // iat (device clock ahead — `ageH < 0`) is a *different* problem and
  // gets its own message so we don't mislead the user into recapturing
  // a token whose real issue is the device clock.
  const showStaleStale =
    typeof ageH === "number" && ageH > 4;
  const showStaleFuture =
    typeof ageH === "number" && ageH < 0;
  const showCountdown =
    detail.code === "grab_rate_limited" &&
    typeof detail.retry_after_seconds === "number" &&
    detail.retry_after_seconds > 0 &&
    !!onAutoRetry;
  return (
    <div
      role="alert"
      aria-live="polite"
      className={`flex items-start gap-3 rounded-md border px-3 py-2.5 text-sm ${className}`}
    >
      <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex items-center justify-between gap-2">
          <p className="font-medium">{label}</p>
          {detail.request_id && (
            <span className="font-mono text-[10px] opacity-60">
              req: {detail.request_id.slice(0, 12)}
            </span>
          )}
        </div>
        <p className="leading-relaxed">{detail.message}</p>
        {detail.hint && (
          <p className="text-xs leading-relaxed opacity-80">{detail.hint}</p>
        )}
        {showStaleStale && (
          <p className="mt-1 flex items-center gap-1.5 rounded border border-current/20 bg-current/5 px-2 py-1 text-xs leading-relaxed">
            <Timer className="h-3 w-3 shrink-0" aria-hidden />
            x-ray đã {ageH!.toFixed(1)}h tuổi. HMAC của Grab hết hạn sau vài giờ — hãy lấy lại
            trước lần thử tiếp theo, nếu không khoảng đợi 5 phút sẽ không có tác dụng.
          </p>
        )}
        {showStaleFuture && (
          <p className="mt-1 flex items-center gap-1.5 rounded border border-current/20 bg-current/5 px-2 py-1 text-xs leading-relaxed">
            <Timer className="h-3 w-3 shrink-0" aria-hidden />
            x-ray được phát hành {Math.abs(ageH!).toFixed(1)}h trong tương lai —
            đồng hồ thiết bị của bạn chạy nhanh hơn máy chủ Grab. Đồng bộ
            đồng hồ thiết bị qua NTP, rồi lấy lại token.
          </p>
        )}
        {showCountdown && (
          <RetryCountdown
            seconds={detail.retry_after_seconds!}
            onElapsed={onAutoRetry!}
          />
        )}
      </div>
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Dismiss error"
        className="shrink-0 rounded p-1 opacity-60 transition hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-current"
      >
        <XCircle className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

/**
 * Tick-down timer that fires `onElapsed` once. Mirrors a typical
 * "Resend code in 30s" pattern: we update `remaining` every second so the
 * label stays accurate, but `setTimeout` only arms once. Cancels itself
 * if the banner unmounts (component dismount, user dismisses, etc.).
 *
 * `seconds` is intentionally the only effect dep so the timer only
 * re-arms when the backend tells us a new countdown window — otherwise
 * every parent re-render would reset the visible counter and the
 * schedule would drift. The `firedRef` guard prevents double-fire under
 * React StrictMode's dev-only double-invoke.
 */
function RetryCountdown({
  seconds,
  onElapsed,
}: {
  seconds: number;
  onElapsed: () => void;
}) {
  const [remaining, setRemaining] = React.useState(seconds);
  const firedRef = React.useRef(false);
  React.useEffect(() => {
    setRemaining(seconds);
    firedRef.current = false;
    const tick = window.setInterval(() => {
      setRemaining((r) => Math.max(0, r - 1));
    }, 1000);
    const fire = window.setTimeout(() => {
      if (firedRef.current) return;
      firedRef.current = true;
      onElapsed();
    }, seconds * 1000);
    return () => {
      window.clearInterval(tick);
      window.clearTimeout(fire);
    };
    // `seconds` comes from the backend detail envelope and is stable for
    // the lifetime of this banner instance; the linter still wants it in
    // the dep array so future changes don't silently desync.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seconds]);
  const mm = Math.floor(remaining / 60);
  const ss = remaining % 60;
  return (
    <p className="mt-1 flex items-center gap-1.5 text-xs leading-relaxed opacity-80">
      <Timer className="h-3 w-3 shrink-0" aria-hidden />
      Tự động thử lại sau{" "}
      <span className="font-mono tabular-nums">
        {mm}:{ss.toString().padStart(2, "0")}
      </span>
      …
    </p>
  );
}