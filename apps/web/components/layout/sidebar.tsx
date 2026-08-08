"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Award,
  ClipboardList,
  DollarSign,
  LayoutDashboard,
  Megaphone,
  Settings,
  ShoppingBag,
  Users,
} from "lucide-react";
import {
  Sidebar as SidebarPrimitive,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
  SidebarTrigger,
  useSidebar,
} from "@/components/ui/sidebar";
import { BrandLogo } from "@/components/layout/brand-logo";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface NavItem {
  href: string;
  label: string;
  icon: typeof LayoutDashboard;
  /** When set, the link matches if the active path starts with this prefix. */
  matchPrefix?: boolean;
}

const NAV: NavItem[] = [
  { href: "/dashboard", label: "Tổng quan", icon: LayoutDashboard },
  // "Tùy chọn thêm" is now a tab inside Thực đơn, not its own entry —
  // menu building lives in one place.
  { href: "/menu", label: "Thực đơn", icon: ShoppingBag, matchPrefix: true },
  { href: "/orders", label: "Đơn hàng", icon: ClipboardList },
  { href: "/finance", label: "Tài chính", icon: DollarSign },
  { href: "/marketing", label: "Tiếp thị", icon: Megaphone },
  // Stores page removed — login creates exactly one store per account.
  { href: "/golden-apron", label: "Tạp Dề Vàng", icon: Award },
  { href: "/customers", label: "Khách hàng & Nguồn", icon: Users },
];

const FOOTER: NavItem[] = [
  { href: "/settings", label: "Cài đặt", icon: Settings },
];

function isActive(pathname: string | null, item: NavItem): boolean {
  if (!pathname) return false;
  if (item.matchPrefix) return pathname === item.href || pathname.startsWith(`${item.href}/`);
  return pathname === item.href;
}

/**
 * Primary nav rail. Renders inside the dashboard route group's
 * `<SidebarProvider>`. Collapses to icon-only via the shadcn `icon`
 * collapsible mode + keyboard shortcut (⌘/Ctrl+B).
 *
 * The custom collapse button at the bottom is a redundant entry point
 * — the rail itself is the primary control.
 */
export function Sidebar() {
  const pathname = usePathname();
  const { state } = useSidebar();
  const collapsed = state === "collapsed";

  return (
    <SidebarPrimitive collapsible="icon" variant="sidebar">
      <SidebarHeader>
        <BrandLogo collapsed={collapsed} />
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Không gian làm việc</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {NAV.map((item) => (
                <SidebarMenuItem key={item.href}>
                  <SidebarMenuButton
                    tooltip={item.label}
                    isActive={isActive(pathname, item)}
                    render={
                      <Link href={item.href}>
                        <item.icon />
                        <span>{item.label}</span>
                      </Link>
                    }
                  />
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter>
        <SidebarMenu>
          {FOOTER.map((item) => (
            <SidebarMenuItem key={item.href}>
              <SidebarMenuButton
                tooltip={item.label}
                isActive={isActive(pathname, item)}
                render={
                  <Link href={item.href}>
                    <item.icon />
                    <span>{item.label}</span>
                  </Link>
                }
              />
            </SidebarMenuItem>
          ))}
        </SidebarMenu>
      </SidebarFooter>

      <SidebarRail />
    </SidebarPrimitive>
  );
}

/**
 * The collapse toggle surfaced in the topbar. Uses shadcn's
 * `SidebarTrigger` so it shares the same keyboard shortcut (⌘/Ctrl+B).
 */
export function SidebarToggle({ className }: { className?: string }) {
  return (
    <SidebarTrigger
      className={cn(
        "text-(--color-muted-foreground) hover:text-(--color-foreground)",
        className
      )}
    />
  );
}

// Re-export so the topbar can show its own manual fallback button if it
// wants to render a hamburger glyph alongside the shadcn trigger.
export function HamburgerIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <line x1="3" y1="6" x2="21" y2="6" />
      <line x1="3" y1="12" x2="21" y2="12" />
      <line x1="3" y1="18" x2="21" y2="18" />
    </svg>
  );
}