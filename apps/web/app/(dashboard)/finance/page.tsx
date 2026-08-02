import { PageHeader } from "@/components/layout/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { DollarSign, TrendingUp, Wallet } from "lucide-react";

export default function FinancePage() {
  return (
    <div className="space-y-6 p-6">
      <PageHeader
        title="Tài chính"
        description="Theo dõi doanh thu, rút tiền và lịch sử thanh toán từ Grab."
      />

      <div className="grid gap-4 md:grid-cols-3">
        <Card className="border-(--color-border)">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Doanh thu hôm nay</CardTitle>
            <DollarSign className="h-4 w-4 text-(--color-muted-foreground)" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-(--color-brand)">— ₫</div>
            <p className="mt-1 text-xs text-(--color-muted-foreground)">
              Đang đồng bộ từ Grab Merchant…
            </p>
          </CardContent>
        </Card>

        <Card className="border-(--color-border)">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Doanh thu tuần</CardTitle>
            <TrendingUp className="h-4 w-4 text-(--color-muted-foreground)" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-(--color-foreground)">— ₫</div>
            <p className="mt-1 text-xs text-(--color-muted-foreground)">
              Sẽ hiển thị khi endpoint được kết nối.
            </p>
          </CardContent>
        </Card>

        <Card className="border-(--color-border)">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Số dư khả dụng</CardTitle>
            <Wallet className="h-4 w-4 text-(--color-muted-foreground)" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-(--color-foreground)">— ₫</div>
            <p className="mt-1 text-xs text-(--color-muted-foreground)">
              Đang đợi dữ liệu từ Grab Finance API.
            </p>
          </CardContent>
        </Card>
      </div>

      <div className="rounded-xl border border-(--color-border) bg-(--color-surface) p-10 text-center text-(--color-muted-foreground)">
        Module <strong>Tài chính</strong> đang được phát triển. Các chỉ số doanh thu, lịch sử thanh toán và yêu cầu rút tiền sẽ được đồng bộ từ Grab Finance API trong phase tiếp theo.
      </div>
    </div>
  );
}