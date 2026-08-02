"use client";

import { useEffect } from "react";
import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";

/**
 * App-level error boundary. Next.js' App Router picks this up automatically
 * for any unhandled error in a server or client component below it.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Log to console for now; could fan out to Sentry/etc. later.
    console.error("App error boundary caught:", error);
  }, [error]);

  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4 p-8 text-center">
      <div className="rounded-full bg-red-500/10 p-3 text-red-500">
        <AlertTriangle className="h-8 w-8" />
      </div>
      <div className="space-y-1">
        <h1 className="text-xl font-semibold text-(--color-foreground)">
          Đã xảy ra lỗi trên trang này
        </h1>
        <p className="max-w-md text-sm text-(--color-muted-foreground)">
          {error.message || "Đã xảy ra lỗi không mong muốn. Bạn có thể thử lại, hoặc quay về dashboard."}
        </p>
        {error.digest && (
          <p className="font-mono text-xs text-(--color-muted-foreground)">
            digest: {error.digest}
          </p>
        )}
      </div>
      <div className="flex gap-2">
        <Button variant="outline" onClick={() => (window.location.href = "/dashboard")}>
          Về dashboard
        </Button>
        <Button
          onClick={() => reset()}
          className="bg-(--color-brand) text-white hover:bg-(--color-brand-hover)"
        >
          Thử lại
        </Button>
      </div>
    </div>
  );
}
