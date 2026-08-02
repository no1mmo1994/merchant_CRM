"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useSelectStore, useStore } from "@/lib/api/stores";
import { useUIStore } from "@/lib/stores/ui-store";
import { toast } from "sonner";

interface StoreDetailClientProps {
  merchantId: string;
}

export function StoreDetailClient({ merchantId }: StoreDetailClientProps) {
  const router = useRouter();
  const { data, isLoading, isError, error } = useStore(merchantId);
  const selectMutation = useSelectStore();
  const setActiveStoreId = useUIStore((s) => s.setActiveStoreId);
  const setActiveStoreName = useUIStore((s) => s.setActiveStoreName);

  React.useEffect(() => {
    if (isError) toast.error(error instanceof Error ? error.message : "Không thể tải cửa hàng");
  }, [isError, error]);

  async function handleActivate() {
    if (!data) return;
    try {
      await selectMutation.mutateAsync(merchantId);
      setActiveStoreId(String(data.store.id));
      setActiveStoreName(data.store.name);
      toast.success(`Cửa hàng hoạt động: ${data.store.name}`);
      router.refresh();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Không thể chuyển cửa hàng");
    }
  }

  if (isLoading) {
    return (
      <div className="grid gap-4 md:grid-cols-2">
        <Skeleton className="h-64" />
        <Skeleton className="h-64" />
      </div>
    );
  }
  if (isError || !data) {
    return (
      <div className="rounded-lg border border-(--color-border) bg-(--color-surface) p-6 text-sm text-(--color-muted-foreground)">
        Không thể tải cửa hàng này.
      </div>
    );
  }

  const { store, business_attributes, scorecard } = data;

  return (
    <div className="space-y-4">
      <Button variant="ghost" size="sm" onClick={() => router.back()}>
        <ArrowLeft className="mr-1.5 h-4 w-4" />
        Quay lại
      </Button>

      <div className="grid gap-4 md:grid-cols-2">
        <Card className="border-(--color-border)">
          <CardHeader>
            <CardTitle>{store.name}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <Field label="Merchant ID" value={store.merchant_id} mono />
            <Field label="Địa chỉ" value={store.address || "—"} />
            <Field label="Ngày tạo" value={new Date(store.created_at).toLocaleString("vi-VN")} />
            <Field
              label="Làm mới token lần cuối"
              value={store.last_refresh_at ? new Date(store.last_refresh_at).toLocaleString("vi-VN") : "Chưa từng"}
            />
          </CardContent>
          <div className="flex justify-end p-4 pt-0">
            <Button
              onClick={handleActivate}
              disabled={selectMutation.isPending}
              className="bg-(--color-brand) text-white hover:bg-(--color-brand-hover)"
            >
              {selectMutation.isPending ? "Đang chuyển…" : "Kích hoạt"}
            </Button>
          </div>
        </Card>

        <Card className="border-(--color-border)">
          <CardHeader>
            <CardTitle>Bảng đánh giá</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {Object.entries(scorecard).length === 0 && (
              <div className="text-(--color-muted-foreground)">Không có dữ liệu đánh giá.</div>
            )}
            {Object.entries(scorecard).map(([k, v]) => (
              <Field key={k} label={k} value={formatValue(v)} />
            ))}
          </CardContent>
        </Card>

        <Card className="border-(--color-border) md:col-span-2">
          <CardHeader>
            <CardTitle>Thuộc tính kinh doanh</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-2 text-sm sm:grid-cols-2">
            {Object.entries(business_attributes).length === 0 && (
              <div className="text-(--color-muted-foreground)">Không có thuộc tính trả về.</div>
            )}
            {Object.entries(business_attributes).map(([k, v]) => (
              <Field key={k} label={k} value={formatValue(v)} />
            ))}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function Field({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex justify-between gap-4 border-b border-dashed border-(--color-border) py-1.5 last:border-0">
      <span className="text-xs uppercase tracking-wider text-(--color-muted-foreground)">{label}</span>
      <span className={mono ? "font-mono text-xs" : "text-(--color-foreground)"}>{value}</span>
    </div>
  );
}

function formatValue(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}
