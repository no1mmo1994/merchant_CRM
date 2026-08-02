"use client";

import * as React from "react";
import { Store as StoreIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useStores } from "@/lib/api/stores";
import { useUIStore } from "@/lib/stores/ui-store";

/**
 * Single-store static badge for the topbar.
 *
 * In single-store mode login creates exactly one Store row per account,
 * so there's nothing to switch. We show the store name + merchant_id
 * from the first (and only) store returned by `GET /api/stores`.
 *
 * No dropdown, no selection, no misleading error/loading state.
 */
export function StoreSwitcher() {
  const { data: stores, isLoading, isError } = useStores();
  const activeStoreName = useUIStore((s) => s.activeStoreName);
  const setActiveStoreName = useUIStore((s) => s.setActiveStoreName);
  const [mounted, setMounted] = React.useState(false);
  React.useEffect(() => setMounted(true), []);

  // Stamp the single store name into the UI store so child components
  // that read activeStoreName from Zustand don't show "—" before hydration.
  React.useEffect(() => {
    if (!mounted || !stores || stores.length === 0) return;
    if (!activeStoreName) {
      setActiveStoreName(stores[0].name);
    }
  }, [mounted, stores, activeStoreName, setActiveStoreName]);

  if (!mounted || isLoading) {
    return <Skeleton className="h-9 w-48" />;
  }

  if (isError || !stores || stores.length === 0) {
    // Single-store login should always produce at least one row, but
    // surface a clear error if something went wrong on the API side.
    return (
      <Badge variant="outline" className="h-9 gap-1.5 border-red-500/50 px-3 text-xs text-red-500">
        <StoreIcon className="h-3.5 w-3.5" />
        Chưa kết nối cửa hàng
      </Badge>
    );
  }

  const store = stores[0];

  return (
    <Badge
      variant="outline"
      className="h-9 gap-1.5 border-(--color-border) bg-(--color-surface-2) px-3 text-xs text-(--color-foreground)"
    >
      <StoreIcon className="h-3.5 w-3.5 shrink-0 text-(--color-brand)" />
      <span className="max-w-36 truncate font-medium">{store.name}</span>
      <span className="max-w-24 truncate font-mono text-(--color-muted-foreground)">
        {store.merchant_id}
      </span>
    </Badge>
  );
}
