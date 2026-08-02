"use client";

import { motion, useReducedMotion } from "framer-motion";
import * as React from "react";

/**
 * Page-level wrapper that fades + slides children in. Respects
 * `prefers-reduced-motion` by zeroing out transforms and durations.
 */
export function PageTransition({ children }: { children: React.ReactNode }) {
  const reducedMotion = useReducedMotion();

  return (
    <motion.div
      initial={reducedMotion ? { opacity: 0 } : { opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: reducedMotion ? 0 : 0.25, ease: [0.16, 1, 0.3, 1] }}
    >
      {children}
    </motion.div>
  );
}
