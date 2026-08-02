"use client";

import * as React from "react";
import { SidebarProvider, SidebarInset } from "@/components/ui/sidebar";
import { Sidebar } from "@/components/layout/sidebar";
import { Topbar } from "@/components/layout/topbar";
import { PageTransition } from "@/components/feedback/PageTransition";
import { DashboardAuthGuard } from "@/components/auth/DashboardAuthGuard";
import { LogoutBlocker } from "@/components/auth/LogoutBlocker";

/**
 * Authenticated app shell. Lives under the `(dashboard)` route group so
 * the marketing landing page (`/`) stays on its own layout.
 *
 * SidebarProvider manages collapse state + cookie persistence; we read
 * it in the Topbar to align the trigger button.
 *
 * Auth stack:
 *   - `LogoutBlocker` shows a non-dismissible overlay while logout is
 *     in flight so the user can't click sidebar items / type in forms
 *     on the way out.
 *   - `DashboardAuthGuard` watches `/api/auth/me` + the local Zustand
 *     store and force-redirects to /login (via window.location) the
 *     moment the session is gone.
 */
export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <DashboardAuthGuard>
      <LogoutBlocker>
        <SidebarProvider
          defaultOpen={true}
          style={
            {
              "--sidebar-width": "16rem",
              "--sidebar-width-icon": "3.5rem",
            } as React.CSSProperties
          }
        >
          <Sidebar />
          <SidebarInset>
            <Topbar />
            <div className="flex-1 overflow-y-auto bg-(--color-background) text-(--color-foreground)">
              <PageTransition>{children}</PageTransition>
            </div>
          </SidebarInset>
        </SidebarProvider>
      </LogoutBlocker>
    </DashboardAuthGuard>
  );
}