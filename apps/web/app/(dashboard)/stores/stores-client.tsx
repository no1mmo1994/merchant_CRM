"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { MapPin, RefreshCw, Star } from "lucide-react";
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useSelectStore, useStores } from "@/lib/api/stores";
import { useUIStore } from "@/lib/stores/ui-store";
import { toast } from "sonner";

export function StoresClient() {
  const router = useRouter();
  const { data: stores, isLoading, isError, error, refetch, isRefetching } = useStores();
  const selectMutation = useSelectStore();
  const setActiveStoreId = useUIStore((s) => s.setActiveStoreId);
  const setActiveStoreName = useUIStore((s) => s.setActiveStoreName);
  const activeStoreId = useUIStore((s) => s.activeStoreId);

  React.useEffect(() => {
    if (isError) toast.error(error instanceof Error ? error.message : "Không thể tải cửa hàng");
  }, [isError, error]);

  async function handleActivate(merchantId: string, id: number, name: string) {
    try {
      await selectMutation.mutateAsync(merchantId);
      setActiveStoreId(String(id));
      setActiveStoreName(name);
      toast.success(`Cửa hàng hoạt động: ${name}`);
      router.refresh();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Không thể chuyển cửa hàng");
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="text-sm text-(--color-muted-foreground)">
          {stores?.length ?? 0} cửa hàng đã kết nối.
        </div>
        <Button variant="outline" size="sm" onClick={() => refetch()} disabled={isRefetching}>
          <RefreshCw className={`mr-1.5 h-3.5 w-3.5 ${isRefetching ? "animate-spin" : ""}`} />
          Làm mới
        </Button>
      </div>

      {isLoading && (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-44 w-full" />
          ))}
        </div>
      )}

      {!isLoading && (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {stores?.map((store) => {
            const isActive = String(store.id) === activeStoreId;
            return (
              <Card
                key={store.id}
                className={[
                  "border transition-colors",
                  isActive ? "border-(--color-brand)" : "border-(--color-border)",
                ].join(" ")}
              >
                <CardHeader className="space-y-1">
                  <div className="flex items-center justify-between gap-2">
                    <CardTitle className="truncate">{store.name}</CardTitle>
                    {isActive ? <Badge className="bg-(--color-brand) text-white">Đang hoạt động</Badge> : null}
                  </div>
                  <div className="flex items-center gap-1.5 text-xs text-(--color-muted-foreground)">
                    <MapPin className="h-3 w-3" />
                    <span className="truncate">{store.address || `merchant ${store.merchant_id}`}</span>
                  </div>
                </CardHeader>
                <CardContent className="space-y-2 text-sm text-(--color-muted-foreground)">
                  <div className="font-mono text-xs">{store.merchant_id}</div>
                  <div className="flex items-center gap-1 text-xs">
                    <Star className="h-3 w-3 text-amber-500" />
                    {store.last_refresh_at
                      ? `Token đã làm mới ${new Date(store.last_refresh_at).toLocaleString("vi-VN")}`
                      : "Token chưa từng làm mới"}
                  </div>
                </CardContent>
                <CardFooter className="justify-end gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => router.push(`/stores/${store.merchant_id}`)}
                  >
                    Chi tiết
                  </Button>
                  <Button
                    size="sm"
                    disabled={isActive || selectMutation.isPending}
                    onClick={() => handleActivate(store.merchant_id, store.id, store.name)}
                    className="bg-(--color-brand) text-white hover:bg-(--color-brand-hover)"
                  >
                    {isActive ? "Đang hoạt động" : selectMutation.isPending ? "Đang chuyển…" : "Kích hoạt"}
                  </Button>
                </CardFooter>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
