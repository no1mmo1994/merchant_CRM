"use client";

import * as React from "react";
import { QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "sonner";

import { createQueryClient } from "@/lib/query-client";
import { ThemeProvider } from "@/components/theme-provider";
import { AuthBoot } from "@/components/auth/AuthBoot";

/**
 * Top-level client providers for the PulseOrder app.
 *
 * Mounted once at the root layout. QueryClient is created lazily per
 * browser session so SSR / HMR don't share state across requests.
 *
 * - `AuthBoot` hydrates the auth Zustand store from `/api/auth/me` on
 *   app boot so the sidebar UserMenu can read user state synchronously.
 * - `Toaster` is the shared sonner toast portal (used by LoginForm,
 *   logout, future destructive actions).
 */
export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = React.useState(() => createQueryClient());
  return (
    <QueryClientProvider client={client}>
      <ThemeProvider
        attribute="class"
        defaultTheme="system"
        enableSystem
        disableTransitionOnChange
      >
        <AuthBoot />
        {children}
        <Toaster
          richColors
          position="top-right"
          toastOptions={{
            className: "font-sans",
          }}
        />
      </ThemeProvider>
    </QueryClientProvider>
  );
}
