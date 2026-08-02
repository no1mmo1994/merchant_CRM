"use client";

import Link from "next/link";
import { cn } from "@/lib/utils";

interface BrandLogoProps {
  collapsed?: boolean;
  className?: string;
}

/**
 * PulseOrder wordmark + a small pulsing-wave icon.
 * Two variants: full (icon + text) and compact (icon only for the
 * collapsed sidebar).
 *
 * Brand orange `#F26B3A` is fixed across light and dark themes.
 */
export function BrandLogo({ collapsed = false, className }: BrandLogoProps) {
  return (
    <Link
      href="/dashboard"
      className={cn(
        "flex items-center gap-2 rounded-md px-2 py-1.5",
        "transition-colors hover:bg-(--color-surface-2)",
        className
      )}
      aria-label="PulseOrder home"
    >
      <PulseMark className="h-6 w-6 shrink-0" />
      {!collapsed && (
        <span className="text-base font-bold tracking-tight text-(--color-foreground)">
          PulseOrder
        </span>
      )}
    </Link>
  );
}

function PulseMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-hidden="true"
    >
      <rect width="24" height="24" rx="6" fill="#F26B3A" />
      <path
        d="M3 12h3l2-5 3 10 2-7 2 4h6"
        stroke="white"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}