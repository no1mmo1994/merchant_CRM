import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Combines clsx + tailwind-merge for conflict-free className composition.
 * Use as: `cn("p-4 text-sm", condition && "bg-red-500")`
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
