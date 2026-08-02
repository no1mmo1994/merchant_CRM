import { DashboardSkeleton } from "@/components/feedback/DashboardSkeleton";

/**
 * App-level loading state. Next.js renders this while route segments
 * are streaming in.
 */
export default function Loading() {
  return (
    <div className="space-y-6 p-6">
      <div className="space-y-2">
        <div className="h-7 w-40 animate-pulse rounded-md bg-(--color-surface-2)" />
        <div className="h-4 w-72 animate-pulse rounded-md bg-(--color-surface-2)" />
      </div>
      <DashboardSkeleton />
    </div>
  );
}
