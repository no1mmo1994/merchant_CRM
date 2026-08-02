import type { Variants } from "framer-motion";

/**
 * Reusable Framer Motion variants. All exit/entrance timings are
 * short enough to feel snappy (< 0.5s) but long enough to read.
 *
 * Convention: children inherit `variants` from a parent with
 * `staggerContainer` and use `fadeUp` for their own definition.
 */

export const fadeUp: Variants = {
  hidden: { opacity: 0, y: 16 },
  show: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.4, ease: [0.16, 1, 0.3, 1] },
  },
};

export const staggerContainer: Variants = {
  hidden: {},
  show: {
    transition: {
      delayChildren: 0.05,
      staggerChildren: 0.06,
    },
  },
};

export const fadeIn: Variants = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { duration: 0.3 } },
};

export const slideDown: Variants = {
  hidden: { opacity: 0, y: -8 },
  show: { opacity: 1, y: 0, transition: { duration: 0.35, ease: [0.16, 1, 0.3, 1] } },
};
