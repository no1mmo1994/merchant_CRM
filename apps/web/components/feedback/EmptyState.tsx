"use client";

import * as React from "react";
import { motion, useReducedMotion } from "framer-motion";
import { Inbox } from "lucide-react";

interface EmptyStateProps {
  icon?: React.ReactNode;
  title: string;
  description?: string;
  action?: React.ReactNode;
}

/**
 * Reusable empty-state block. Respects `prefers-reduced-motion`: when the
 * user has reduced motion enabled, the entrance animation is skipped.
 */
export function EmptyState({ icon, title, description, action }: EmptyStateProps) {
  const reducedMotion = useReducedMotion();

  return (
    <motion.div
      initial={reducedMotion ? false : { opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: reducedMotion ? 0 : 0.3 }}
      className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-(--color-border) bg-(--color-surface) p-10 text-center"
    >
      <div className="rounded-full bg-(--color-surface-2) p-3 text-(--color-muted-foreground)">
        {icon ?? <Inbox className="h-6 w-6" />}
      </div>
      <div className="text-sm font-medium text-(--color-foreground)">{title}</div>
      {description && (
        <div className="max-w-sm text-sm text-(--color-muted-foreground)">{description}</div>
      )}
      {action && <div className="mt-2">{action}</div>}
    </motion.div>
  );
}
