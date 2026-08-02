"use client";

import * as React from "react";
import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";

interface ErrorStateProps {
  title?: string;
  message?: string;
  onRetry?: () => void;
}

/**
 * Standard error state for failed queries. Not a route error boundary —
 * pair with `app/error.tsx` for unhandled crashes.
 */
export function ErrorState({
  title = "Đã xảy ra lỗi",
  message = "Vui lòng thử lại sau.",
  onRetry,
}: ErrorStateProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-red-500/30 bg-red-500/5 p-10 text-center">
      <div className="rounded-full bg-red-500/10 p-3 text-red-500">
        <AlertTriangle className="h-6 w-6" />
      </div>
      <div className="text-sm font-medium text-(--color-foreground)">{title}</div>
      <div className="max-w-sm text-sm text-(--color-muted-foreground)">{message}</div>
      {onRetry && (
        <Button size="sm" variant="outline" onClick={onRetry}>
          Thử lại
        </Button>
      )}
    </div>
  );
}
