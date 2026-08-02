import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * Skeleton placeholder for the dashboard. Mirrors the DashboardGrid
 * layout (8/4 + 4/4/4 + 8/4 + 12) so the page doesn't jump.
 */
export function DashboardSkeleton() {
  return (
    <div className="grid grid-cols-12 gap-6">
      <Skeleton className="lg:col-span-8 h-40" />
      <Skeleton className="lg:col-span-4 h-40" />
      <Skeleton className="lg:col-span-4 h-28" />
      <Skeleton className="lg:col-span-4 h-28" />
      <Skeleton className="lg:col-span-4 h-28" />
      <Skeleton className="lg:col-span-8 h-72" />
      <Skeleton className="lg:col-span-4 h-72" />
      <Card className="lg:col-span-12 border-(--color-border)">
        <CardHeader><Skeleton className="h-5 w-32" /></CardHeader>
        <CardContent className="space-y-2">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </CardContent>
      </Card>
    </div>
  );
}
