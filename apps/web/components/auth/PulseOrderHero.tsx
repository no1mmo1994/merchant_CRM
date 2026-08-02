import { BrandLogo } from "./BrandLogo";

/**
 * Decorative left panel of the auth layout. Plays the role of a marketing
 * surface during login; uses CSS only (no Framer Motion) so the bundle
 * stays light and there's no SSR/hydration risk.
 *
 * - Brand wordmark + tagline
 * - 3 feature bullets
 * - Subtle radial gradient that works in both light and dark mode
 */
export function PulseOrderHero() {
  return (
    <aside
      aria-hidden="false"
      className="relative hidden overflow-hidden bg-gradient-to-br from-[#F26B3A] via-[#F26B3A]/85 to-[#B8472A] text-white lg:flex lg:flex-col lg:justify-between lg:p-10"
    >
      {/* Decorative ring */}
      <div className="pointer-events-none absolute -right-32 -top-32 h-96 w-96 rounded-full bg-white/10 blur-3xl" />
      <div className="pointer-events-none absolute -bottom-40 -left-20 h-80 w-80 rounded-full bg-black/15 blur-3xl" />

      <BrandLogo size={36} className="relative text-white [&_span]:!text-white" />

      <div className="relative max-w-md space-y-6">
        <h1 className="text-4xl font-semibold leading-tight tracking-tight">
          Quản lý tất cả cửa hàng Grab Merchant của bạn trong một nhịp.
        </h1>
        <p className="text-base text-white/85">
          Đồng bộ thực đơn, tùy chọn thêm và giá cả trên mọi cửa hàng bạn vận hành — không cần mở nhiều tab.
        </p>

        <ul className="space-y-2 text-sm text-white/90">
          <li className="flex items-start gap-2">
            <Check /> Lưu trữ token được mã hóa — x-ray không bao giờ rời khỏi máy của bạn dạng rõ.
          </li>
          <li className="flex items-start gap-2">
            <Check /> Một dashboard, nhiều cửa hàng, một chu kỳ làm mới.
          </li>
          <li className="flex items-start gap-2">
            <Check /> Nhật ký hoạt động &amp; lịch đồng bộ cho từng cửa hàng (Giai đoạn 10/11).
          </li>
        </ul>
      </div>

      <p className="relative text-xs text-white/70">
        PulseOrder là công cụ cá nhân. Thông tin đăng nhập Grab của bạn được gửi đến Grab Merchant API
        tại Singapore; token được mã hóa bằng Fernet và lưu trữ cục bộ.
      </p>
    </aside>
  );
}

function Check() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="mt-0.5 shrink-0"
    >
      <polyline points="20 6 9 17 4 12" />
    </svg>
  );
}
