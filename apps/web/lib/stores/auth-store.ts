"use client";

import { create } from "zustand";
import type { AuthUser, AuthStore } from "@/lib/api/auth";

/**
 * Client-side mirror of the authenticated session. Hydrated from
 * `useMe()` (which itself reads the backend's httponly cookie) and
 * cleared by `useLogout()` on success.
 *
 * Kept in Zustand so non-React components (e.g. middleware-style guards
 * in route guards) and the UserMenu can read auth state synchronously
 * without each spinning up their own useQuery.
 */
interface AuthState {
  user: AuthUser | null;
  stores: AuthStore[];
  setSession: (user: AuthUser, stores: AuthStore[]) => void;
  clear: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  stores: [],
  setSession: (user, stores) => set({ user, stores }),
  clear: () => set({ user: null, stores: [] }),
}));