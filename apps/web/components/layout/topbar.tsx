"use client";

import * as React from "react";
import { usePathname } from "next/navigation";
import { ChevronRight } from "lucide-react";
import { SidebarToggle } from "@/components/layout/sidebar";
import { StoreSwitcher } from "@/components/layout/store-switcher";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { UserMenu } from "@/components/layout/user-menu";
import { ConnectionStatusBadge } from "@/components/layout/connection-status-badge";

/**
 * Topbar for the dashboard route group. Houses:
 *   - sidebar collapse trigger (left)
 *   - breadcrumb (center-left)
 *   - store switcher (center)
 *   - theme toggle + user menu (right)
 *
 * No client-side data fetching here in Phase 04 — store switcher is a
 * placeholder that defers real wiring to Phase 09.
 */
export function Topbar() {
  const pathname = usePathname();
  const segments = buildBreadcrumb(pathname);

  return (
    <div className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-(--color-border) bg-(--color-background)/80 px-4 backdrop-blur supports-[backdrop-filter]:bg-(--color-background)/60">
      <SidebarToggle />

      <nav
        className="hidden min-w-0 items-center gap-1 text-sm text-(--color-muted-foreground) md:flex"
        aria-label="Breadcrumb"
      >
        {segments.map((seg, idx) => (
          <React.Fragment key={`${seg.href}-${idx}`}>
            {idx > 0 && (
              <ChevronRight className="h-3.5 w-3.5 opacity-50" aria-hidden="true" />
            )}
            <span
              className={
                idx === segments.length - 1
                  ? "font-medium text-(--color-foreground)"
                  : ""
              }
            >
              {seg.label}
            </span>
          </React.Fragment>
        ))}
      </nav>

      <div className="ml-auto flex items-center gap-2">
        <ConnectionStatusBadge />
        <StoreSwitcher />
        <ThemeToggle />
        <UserMenu />
      </div>
    </div>
  );
}

function buildBreadcrumb(pathname: string | null): { label: string; href: string }[] {
  if (!pathname) return [{ label: "Tổng quan", href: "/dashboard" }];
  const parts = pathname.split("/").filter(Boolean);
  if (parts.length === 0) return [{ label: "Tổng quan", href: "/dashboard" }];

  const labels: Record<string, string> = {
    dashboard: "Tổng quan",
    menu: "Thực đơn",
    modifiers: "Tùy chọn thêm",
    stores: "Cửa hàng",
    analytics: "Phân tích",
    settings: "Cài đặt",
  };
  const root = parts[0];
  return [
    { label: labels[root] ?? (root.charAt(0).toUpperCase() + root.slice(1)), href: `/${root}` },
  ];
}