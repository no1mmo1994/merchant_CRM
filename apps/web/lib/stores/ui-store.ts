"use client";

import { create } from "zustand";

/**
 * UI-only state. Persisted to localStorage so sidebar collapse + the
 * active-store selection survive a refresh. Theme is owned by `next-themes`.
 */
interface UIState {
  sidebarCollapsed: boolean;
  toggleSidebar: () => void;
  setSidebarCollapsed: (collapsed: boolean) => void;

  activeStoreId: string | null;
  setActiveStoreId: (id: string | null) => void;

  /** Stores list mirror (synced from /api/auth/me on login + on store pages). */
  activeStoreName: string | null;
  setActiveStoreName: (name: string | null) => void;
}

const STORAGE_KEY = "pulseorder.ui";

function loadInitial(): Pick<UIState, "sidebarCollapsed" | "activeStoreId" | "activeStoreName"> {
  const empty = { sidebarCollapsed: false, activeStoreId: null, activeStoreName: null };
  if (typeof window === "undefined") return empty;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return empty;
    const parsed = JSON.parse(raw) as Partial<UIState>;
    return {
      sidebarCollapsed: Boolean(parsed.sidebarCollapsed),
      activeStoreId: typeof parsed.activeStoreId === "string" ? parsed.activeStoreId : null,
      activeStoreName: typeof parsed.activeStoreName === "string" ? parsed.activeStoreName : null,
    };
  } catch {
    return empty;
  }
}

function persist(state: UIState) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        sidebarCollapsed: state.sidebarCollapsed,
        activeStoreId: state.activeStoreId,
        activeStoreName: state.activeStoreName,
      })
    );
  } catch {
    /* quota exceeded — non-fatal */
  }
}

export const useUIStore = create<UIState>((set) => ({
  ...loadInitial(),
  toggleSidebar: () =>
    set((s) => {
      const next = { ...s, sidebarCollapsed: !s.sidebarCollapsed };
      persist(next);
      return { sidebarCollapsed: next.sidebarCollapsed };
    }),
  setSidebarCollapsed: (collapsed) =>
    set((s) => {
      const next = { ...s, sidebarCollapsed: collapsed };
      persist(next);
      return { sidebarCollapsed: collapsed };
    }),
  activeStoreId: null,
  setActiveStoreId: (id) =>
    set((s) => {
      const next = { ...s, activeStoreId: id };
      persist(next);
      return { activeStoreId: id };
    }),
  activeStoreName: null,
  setActiveStoreName: (name) =>
    set((s) => {
      const next = { ...s, activeStoreName: name };
      persist(next);
      return { activeStoreName: name };
    }),
}));
