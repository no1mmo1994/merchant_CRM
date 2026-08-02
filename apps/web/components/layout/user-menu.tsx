"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { LogOut, Settings, User as UserIcon } from "lucide-react";
import { toast } from "sonner";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useAuthStore } from "@/lib/stores/auth-store";
import { useLogout } from "@/lib/api/auth";
import { clearAuthTokenFailStreak } from "@/hooks/useStoreConnectionStatus";

/**
 * User dropdown — Phase 05 wires logout. Profile/Settings remain
 * placeholders until Phase 10.
 */
export function UserMenu() {
  const router = useRouter();
  const user = useAuthStore((s) => s.user);
  const clear = useAuthStore((s) => s.clear);
  const logout = useLogout();

  const initials = (user?.username ?? "?")
    .split(/[^\p{L}\p{N}]/u)
    .filter(Boolean)
    .map((s) => s[0])
    .join("")
    .slice(0, 2)
    .toUpperCase() || "PO";

  const display = user?.username ?? "Guest";

  function hardRedirectToLogin() {
    if (typeof window === "undefined") {
      router.push("/login");
      return;
    }
    // Full-page navigation is the only reliable way to unmount the
    // (dashboard) layout AND kill any in-flight queries (the user's
    // complaint: after clicking Logout the sidebar stayed clickable
    // for a beat before redirect, so they could poke items in a
    // half-logged-out state).
    window.location.assign("/login");
  }

  function onLogout() {
    clearAuthTokenFailStreak();
    logout.mutate(undefined, {
      onSuccess: () => {
        clear();
        toast.success("Đã đăng xuất.");
        hardRedirectToLogin();
      },
      onError: () => {
        // Even if the API call fails (e.g. 401 — already logged out),
        // ensure local state is clean and we still redirect.
        clear();
        hardRedirectToLogin();
      },
    });
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger className="rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--color-ring)">
        <Avatar className="h-8 w-8">
          <AvatarFallback className="bg-(--color-primary) text-(--color-primary-foreground) text-xs font-semibold">
            {initials}
          </AvatarFallback>
        </Avatar>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuGroup>
          <DropdownMenuLabel>
            <div className="flex flex-col">
              <span className="truncate text-sm font-medium">{display}</span>
              <span className="text-xs text-(--color-muted-foreground)">
                {user ? "Đã đăng nhập" : "Chưa đăng nhập"}
              </span>
            </div>
          </DropdownMenuLabel>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuItem className="flex items-center gap-2" disabled>
          <UserIcon className="h-4 w-4" /> Hồ sơ
        </DropdownMenuItem>
        <DropdownMenuItem className="flex items-center gap-2" disabled>
          <Settings className="h-4 w-4" /> Cài đặt
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          className="flex items-center gap-2 text-(--color-destructive) focus:text-(--color-destructive)"
          onSelect={(event) => {
            event.preventDefault();
            onLogout();
          }}
          disabled={logout.isPending}
        >
          <LogOut className="h-4 w-4" /> {logout.isPending ? "Đang đăng xuất…" : "Đăng xuất"}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}