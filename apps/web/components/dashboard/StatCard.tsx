"use client";

import * as React from "react";
import { motion } from "framer-motion";
import { ArrowDown, ArrowUp, Minus } from "lucide-react";
import { cn } from "@/lib/utils";
import { fadeUp } from "@/lib/animations/variants";
import { formatPercent } from "@/lib/data/placeholder-kpis";

type Accent = "neutral" | "success" | "danger";

interface StatCardProps {
  title: string;
  value: string;
  change?: number;
  icon?: React.ReactNode;
  accent?: Accent;
  footer?: React.ReactNode;
}

/**
 * Reusable stat card. Used 4× on the dashboard grid + injects motion
 * variants so the parent <DashboardGrid> staggerContainer works
 * without each call site wiring motion.div manually.
 */
export function StatCard({
  title,
  value,
  change,
  icon,
  accent = "neutral",
  footer,
}: StatCardProps) {
  return (
    <motion.div
      variants={fadeUp}
      whileHover={{ y: -2 }}
      whileTap={{ scale: 0.99 }}
      className={cn(
        "rounded-2xl border bg-(--color-surface) p-5 shadow-sm transition-shadow hover:shadow-md",
        "border-(--color-border)"
      )}
    >
      <div className="flex items-start justify-between">
        <div className="text-sm font-medium text-(--color-muted-foreground)">{title}</div>
        {icon && <div className="text-(--color-muted-foreground)">{icon}</div>}
      </div>

      <div className="mt-3 text-3xl font-semibold tracking-tight text-(--color-foreground)">
        {value}
      </div>

      <div className="mt-2 flex items-center gap-2">
        {typeof change === "number" && <TrendBadge change={change} />}
        {footer && (
          <span className="text-xs text-(--color-muted-foreground)">{footer}</span>
        )}
      </div>
    </motion.div>
  );
}

function TrendBadge({ change }: { change: number }) {
  const Icon =
    change > 0 ? ArrowUp : change < 0 ? ArrowDown : Minus;
  const tone =
    change > 0
      ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
      : change < 0
        ? "bg-red-500/10 text-red-600 dark:text-red-400"
        : "bg-zinc-500/10 text-zinc-500";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
        tone
      )}
    >
      <Icon className="h-3 w-3" />
      {formatPercent(change)}
    </span>
  );
}
