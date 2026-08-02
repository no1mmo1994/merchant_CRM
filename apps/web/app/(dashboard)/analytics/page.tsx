import { PageHeader } from "@/components/layout/page-header";

export default function AnalyticsPage() {
  return (
    <div className="space-y-6 p-6">
      <PageHeader
        title="Phân tích"
        description="Ảnh chụp nhanh thực đơn và xu hướng (đang phát triển)."
      />
      <div className="rounded-xl border border-(--color-border) bg-(--color-surface) p-10 text-center text-(--color-muted-foreground)">
        Recharts dashboard lands with Phase 06 / 12.
      </div>
    </div>
  );
}