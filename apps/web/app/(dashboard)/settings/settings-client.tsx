"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  Check,
  Copy,
  Eye,
  EyeOff,
  Loader2,
  RefreshCw,
  Store as StoreIcon,
  Trash2,
} from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuthStore } from "@/lib/stores/auth-store";
import { useStores, useStoreInfo, useRevealAuthnToken } from "@/lib/api/stores";
import { useAuditLog, useDeleteStore, useRefreshToken } from "@/lib/api/settings";
import { useUIStore } from "@/lib/stores/ui-store";
import { StoreStatusDialog } from "@/components/stores/StoreStatusDialog";
import { toast } from "sonner";

export function SettingsClient() {
  const router = useRouter();
  const user = useAuthStore((s) => s.user);
  const storesFromAuth = useAuthStore((s) => s.stores);
  const { data: storesData } = useStores();
  const audit = useAuditLog(50, 0);
  const refreshToken = useRefreshToken();
  const deleteStore = useDeleteStore();
  const activeStoreId = useUIStore((s) => s.activeStoreId);
  const activeStores = storesData ?? storesFromAuth;
  const activeStore =
    activeStores.find((s) => String(s.id) === activeStoreId) ?? activeStores[0];

  // Keep active store in sync after a token refresh
  React.useEffect(() => {
    if (refreshToken.isSuccess) {
      toast.success(`Token đã làm mới lúc ${new Date(refreshToken.data.refreshed_at).toLocaleTimeString("vi-VN")}`);
    }
  }, [refreshToken.isSuccess, refreshToken.data]);

  async function handleRefresh(merchantId: string) {
    try {
      await refreshToken.mutateAsync({ merchant_id: merchantId });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Làm mới thất bại");
    }
  }

  async function handleDeleteStore(merchantId: string, name: string) {
    const ok = confirm(
      `XÓA VĨNH VIỄN "${name}" (${merchantId})?\n\nThao tác này xóa token đã mã hóa và nhật ký hoạt động trên máy. Không ảnh hưởng đến Grab.`
    );
    if (!ok) return;
    try {
      await deleteStore.mutateAsync(merchantId);
      toast.success(`Đã xóa "${name}"`);
      router.refresh();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Xóa thất bại");
    }
  }

  return (
    <div className="space-y-6">
      {/* Profile */}
      <Card className="border-(--color-border)">
        <CardHeader>
          <CardTitle>Hồ sơ</CardTitle>
          <CardDescription>Thông tin tài khoản từ phiên đăng nhập hiện tại.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <Row label="ID người dùng" value={user ? String(user.id) : "—"} mono />
          <Row label="Tên đăng nhập" value={user?.username ?? "—"} />
          <Row label="Ngày tham gia" value={user ? new Date(user.created_at).toLocaleString("vi-VN") : "—"} />
        </CardContent>
      </Card>

      {/* Store info + Payout — surfaced from Grab's unified-profile */}
      {activeStore && <StoreInfoSection merchantId={activeStore.merchant_id} />}

      {/* authnToken — decrypted reveal for `Menu/getmenu.py` + `trangchu/get_thongtin_cuahang.py` */}
      {activeStore && <AuthnTokenSection merchantId={activeStore.merchant_id} />}

      {/* Token refresh — single store */}
      {activeStore && (
        <Card className="border-(--color-border)">
          <CardHeader>
            <CardTitle>Làm mới Token</CardTitle>
            <CardDescription>
              Đăng nhập lại Grab để làm mới token đã hết hạn. Sử dụng khi API trả về 401
              hoặc lỗi "token expired".
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex items-center justify-between gap-3 rounded-lg border border-(--color-border) bg-(--color-surface-2) p-3">
              <div>
                <div className="text-sm font-medium text-(--color-foreground)">
                  {activeStore.name}
                </div>
                <div className="font-mono text-xs text-(--color-muted-foreground)">
                  {activeStore.merchant_id}
                </div>
                <div className="mt-1 text-xs text-(--color-muted-foreground)">
                  Làm mới lần cuối:{" "}
                  {activeStore.last_refresh_at
                    ? new Date(activeStore.last_refresh_at).toLocaleString("vi-VN")
                    : "Chưa từng"}
                </div>
              </div>
              <Button
                size="sm"
                variant="outline"
                onClick={() => handleRefresh(activeStore.merchant_id)}
                disabled={refreshToken.isPending}
              >
                {refreshToken.isPending ? (
                  <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                ) : (
                  <RefreshCw className="mr-1.5 h-3.5 w-3.5" />
                )}
                Làm mới
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Store status — Đặt trạng thái quán (BUSY + TEMPPAUSED) */}
      {activeStore && (
        <Card className="border-(--color-border)">
          <CardHeader>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="space-y-1.5">
                <CardTitle>Đặt trạng thái quán</CardTitle>
                <CardDescription>
                  Tạm nghỉ (TEMPPAUSED) theo khoảng thời gian, hoặc đặt chế độ
                  bận (BUSY) với thời gian chuẩn bị cụ thể. Mở lại để trở về
                  hoạt động bình thường.
                </CardDescription>
              </div>
              <StoreStatusDialog
                merchantId={activeStore.merchant_id}
                trigger={
                  <button
                    type="button"
                    className="inline-flex items-center gap-1.5 rounded-md bg-(--color-brand) px-3 py-1.5 text-sm font-medium text-white shadow-sm transition hover:bg-(--color-brand-hover)"
                  >
                    Đặt trạng thái quán
                  </button>
                }
              />
            </div>
          </CardHeader>
        </Card>
      )}

      {/* Activity log */}
      <Card className="border-(--color-border)">
        <CardHeader>
          <CardTitle>Nhật ký hoạt động</CardTitle>
          <CardDescription>
            {audit.data?.entries.length ?? 0} thao tác gần nhất của bạn.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          {audit.isLoading && (
            <div className="space-y-2">
              {[0, 1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-10" />
              ))}
            </div>
          )}
          {!audit.isLoading && (audit.data?.entries.length ?? 0) === 0 && (
            <div className="rounded-lg border border-dashed border-(--color-border) p-6 text-center text-sm text-(--color-muted-foreground)">
              Chưa có hoạt động nào.
            </div>
          )}
          {audit.data?.entries.map((entry) => (
            <div
              key={entry.id}
              className="flex items-center gap-3 rounded-md border border-(--color-border) bg-(--color-surface) px-3 py-2 text-sm"
            >
              <Badge variant="secondary" className="shrink-0">{entry.action}</Badge>
              <span className="truncate text-(--color-muted-foreground)">
                {entry.entity_type}
                {entry.entity_id ? `: ${entry.entity_id}` : ""}
              </span>
              <span className="ml-auto shrink-0 text-xs text-(--color-muted-foreground)">
                {new Date(entry.created_at).toLocaleString("vi-VN")}
              </span>
            </div>
          ))}
        </CardContent>
      </Card>

      {/* Danger zone — single store */}
      {activeStore && (
        <Card className="border-red-500/40">
          <CardHeader>
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-red-500" />
              <CardTitle className="text-red-500">Vùng nguy hiểm</CardTitle>
            </div>
            <CardDescription>
              Xóa vĩnh viễn cửa hàng khỏi PulseOrder. Token đã mã hóa sẽ bị xóa; thao
              tác này không thể hoàn tác.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex items-center justify-between gap-3 rounded-lg border border-red-500/30 bg-red-500/5 p-3">
              <div>
                <div className="text-sm font-medium text-(--color-foreground)">
                  {activeStore.name}
                </div>
                <div className="font-mono text-xs text-(--color-muted-foreground)">
                  {activeStore.merchant_id}
                </div>
              </div>
              <Button
                size="sm"
                variant="outline"
                onClick={() => handleDeleteStore(activeStore.merchant_id, activeStore.name)}
                disabled={deleteStore.isPending}
                className="border-red-500/40 text-red-500 hover:bg-red-500/10 hover:text-red-500"
              >
                <Trash2 className="mr-1.5 h-3.5 w-3.5" />
                Xóa cửa hàng
              </Button>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex justify-between gap-4 border-b border-dashed border-(--color-border) py-1.5 last:border-0">
      <span className="text-xs uppercase tracking-wider text-(--color-muted-foreground)">{label}</span>
      <span className={mono ? "font-mono text-xs" : "text-(--color-foreground)"}>{value}</span>
    </div>
  );
}

/**
 * Combined store info + payout card. Fetches
 * `GET /api/stores/{merchant_id}/info` and renders the two sections the
 * user asked for in `/settings`. Each section degrades gracefully — if
 * Grab returns partial data we render what we got and show a small hint.
 */
function StoreInfoSection({ merchantId }: { merchantId: string }) {
  const { data, isLoading, isError } = useStoreInfo(merchantId);

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
      {/* Store info */}
      <Card className="border-(--color-border)">
        <CardHeader>
          <div className="flex items-center gap-2">
            <StoreIcon className="h-4 w-4 text-(--color-brand)" />
            <CardTitle>Thông tin cửa hàng</CardTitle>
          </div>
          <CardDescription>
            Dữ liệu trực tiếp từ endpoint <span className="font-mono">unified-profile</span> của Grab.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          {isLoading && (
            <div className="space-y-2">
              {[0, 1, 2, 3, 4].map((i) => (
                <Skeleton key={i} className="h-5" />
              ))}
            </div>
          )}
          {isError && (
            <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-3 text-sm text-red-500">
              Không thể kết nối Grab ngay bây giờ. Thử lại sau.
            </div>
          )}
          {data && (
            <>
              <Row label="Tên cửa hàng" value={data.store_info.data.name ?? "—"} />
              <Row label="Trạng thái" value={data.store_info.data.status ?? "—"} />
              <Row label="Địa chỉ" value={data.store_info.data.address ?? "—"} />
              <Row label="Email" value={data.store_info.data.email ?? "—"} mono />
              <Row
                label="Tọa độ"
                value={
                  data.store_info.data.latitude !== null && data.store_info.data.longitude !== null
                    ? `${data.store_info.data.latitude}, ${data.store_info.data.longitude}`
                    : "—"
                }
                mono
              />
              {!data.store_info.ok && data.store_info.error && (
                <div className="mt-2 rounded-md border border-amber-500/30 bg-amber-500/5 p-2 text-xs text-amber-600 dark:text-amber-400">
                  Grab trả về dữ liệu không đầy đủ: {data.store_info.error}
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>

      {/* Payout */}
      <Card className="border-(--color-border)">
        <CardHeader>
          <CardTitle>Thông tin thanh toán</CardTitle>
          <CardDescription>
            Tài khoản ngân hàng và số điện thoại liên hệ của cửa hàng đang hoạt động.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          {isLoading && (
            <div className="space-y-2">
              {[0, 1, 2, 3, 4].map((i) => (
                <Skeleton key={i} className="h-5" />
              ))}
            </div>
          )}
          {isError && (
            <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-3 text-sm text-red-500">
              Không thể kết nối Grab ngay bây giờ. Thử lại sau.
            </div>
          )}
          {data && (
            <>
              <Row label="Điện thoại cửa hàng" value={data.payout.data.store_phone ?? "—"} mono />
              <Row label="Điện thoại chủ sở hữu" value={data.payout.data.owner_phone ?? "—"} mono />
              <Row label="Tên chủ sở hữu" value={data.payout.data.owner_name ?? "—"} />
              <Row label="Ngân hàng" value={data.payout.data.bank_name ?? "—"} />
              <Row
                label="Tên tài khoản"
                value={data.payout.data.bank_account_name ?? "—"}
              />
              <Row
                label="Số tài khoản"
                value={data.payout.data.bank_account_number ?? "—"}
                mono
              />
              {!data.payout.ok && data.payout.error && (
                <div className="mt-2 rounded-md border border-amber-500/30 bg-amber-500/5 p-2 text-xs text-amber-600 dark:text-amber-400">
                  Grab trả về dữ liệu không đầy đủ: {data.payout.error}
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

/**
 * AuthnToken reveal. Click "Show" to fetch the decrypted auth token from
 * `/api/stores/{merchantId}/authn-token` and copy it into
 * `Menu/getmenu.py` / `trangchu/get_thongtin_cuahang.py`. Each reveal
 * writes an audit log entry server-side.
 */
function AuthnTokenSection({ merchantId }: { merchantId: string }) {
  const reveal = useRevealAuthnToken();
  const [revealed, setRevealed] = React.useState(false);
  const [copied, setCopied] = React.useState(false);

  async function handleReveal() {
    try {
      await reveal.mutateAsync(merchantId);
      setRevealed(true);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Không thể hiện token");
    }
  }

  async function handleCopy(token: string) {
    try {
      await navigator.clipboard.writeText(token);
      setCopied(true);
      toast.success("Đã sao chép authn token vào clipboard");
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("Không thể sao chép. Hãy chọn và sao chép thủ công.");
    }
  }

  function handleHide() {
    setRevealed(false);
    setCopied(false);
  }

  return (
    <Card className="border-(--color-border)">
      <CardHeader>
        <CardTitle>Auth token (authnToken)</CardTitle>
        <CardDescription>
          Giải mã phía server và chỉ hiển thị khi bạn nhấn <em>Hiện</em>.
          Sử dụng làm header <span className="font-mono">authorization</span> /
          <span className="font-mono"> x-mts-ssid</span> trong
          <span className="font-mono"> Menu/getmenu.py</span> và
          <span className="font-mono"> trangchu/get_thongtin_cuahang.py</span>.
          Mỗi lần hiện token đều được ghi nhật ký.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-stretch gap-2">
          <code className="flex-1 min-w-0 break-all rounded-md border border-(--color-border) bg-(--color-surface-2) px-3 py-2 font-mono text-xs">
            {revealed && reveal.data ? reveal.data.authn_token : "••••••••••••••••••••••••••••••"}
          </code>
          {revealed && reveal.data ? (
            <>
              <Button
                size="sm"
                variant="outline"
                onClick={() => handleCopy(reveal.data!.authn_token)}
                disabled={copied}
              >
                {copied ? (
                  <>
                    <Check className="mr-1.5 h-3.5 w-3.5" /> Đã sao chép
                  </>
                ) : (
                  <>
                    <Copy className="mr-1.5 h-3.5 w-3.5" /> Sao chép
                  </>
                )}
              </Button>
              <Button size="sm" variant="ghost" onClick={handleHide}>
                <EyeOff className="mr-1.5 h-3.5 w-3.5" /> Ẩn
              </Button>
            </>
          ) : (
            <Button
              size="sm"
              variant="outline"
              onClick={handleReveal}
              disabled={reveal.isPending}
            >
              {reveal.isPending ? (
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
              ) : (
                <Eye className="mr-1.5 h-3.5 w-3.5" />
              )}
              {reveal.isPending ? "Đang giải mã…" : "Hiện"}
            </Button>
          )}
        </div>
        {reveal.isError && (
          <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-3 text-sm text-red-500">
            {reveal.error instanceof Error ? reveal.error.message : "Hiện token thất bại"}
          </div>
        )}
        {revealed && reveal.data?.last_refresh_at && (
          <div className="text-xs text-(--color-muted-foreground)">
            Làm mới lần cuối: {new Date(reveal.data.last_refresh_at).toLocaleString("vi-VN")}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
