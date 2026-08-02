import { PageHeader } from "@/components/layout/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ClipboardList } from "lucide-react";

interface OrderRow {
  id: string;
  customer: string;
  total: string;
  status: "preparing" | "ready" | "delivering" | "completed";
  items: number;
  time: string;
}

const PLACEHOLDER_ORDERS: OrderRow[] = [
  { id: "GRB-20260802-001", customer: "Nguyễn Văn A", total: "120.000đ", status: "preparing", items: 3, time: "5 phút trước" },
  { id: "GRB-20260802-002", customer: "Trần Thị B", total: "85.000đ", status: "ready", items: 2, time: "12 phút trước" },
  { id: "GRB-20260802-003", customer: "Lê Văn C", total: "210.000đ", status: "delivering", items: 5, time: "20 phút trước" },
];

const STATUS_LABEL: Record<OrderRow["status"], { text: string; variant: "default" | "secondary" | "outline" }> = {
  preparing: { text: "Đang chuẩn bị", variant: "default" },
  ready: { text: "Sẵn sàng giao", variant: "secondary" },
  delivering: { text: "Đang giao", variant: "outline" },
  completed: { text: "Hoàn tất", variant: "secondary" },
};

export default function OrdersPage() {
  return (
    <div className="space-y-6 p-6">
      <PageHeader
        title="Đơn hàng"
        description="Danh sách đơn hàng real-time từ Grab Merchant."
      />

      <div className="grid gap-4 md:grid-cols-4">
        {(["preparing", "ready", "delivering", "completed"] as const).map((s) => {
          const count = PLACEHOLDER_ORDERS.filter((o) => o.status === s).length;
          return (
            <Card key={s} className="border-(--color-border)">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium">
                  {STATUS_LABEL[s].text}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{count}</div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      <Card className="border-(--color-border)">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ClipboardList className="h-4 w-4" />
            Đơn hàng gần đây
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="divide-y divide-(--color-border)">
            {PLACEHOLDER_ORDERS.map((o) => {
              const meta = STATUS_LABEL[o.status];
              return (
                <div
                  key={o.id}
                  className="flex items-center justify-between gap-3 py-3 first:pt-0 last:pb-0"
                >
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-(--color-foreground)">
                      {o.customer}
                    </div>
                    <div className="text-xs text-(--color-muted-foreground)">
                      {o.id} · {o.items} món · {o.time}
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <Badge variant={meta.variant}>{meta.text}</Badge>
                    <span className="text-sm font-semibold text-(--color-brand)">
                      {o.total}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      <div className="rounded-xl border border-(--color-border) bg-(--color-surface) p-6 text-center text-sm text-(--color-muted-foreground)">
        Đồng bộ thời gian thực với Grab Merchant Orders API sẽ được kích hoạt khi backend endpoint <code className="rounded bg-(--color-surface-2) px-1.5 py-0.5">/api/orders</code> được triển khai.
      </div>
    </div>
  );
}