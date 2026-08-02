import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";

/**
 * Menu management API surface.
 *
 * Mirrors the FastAPI routers in services/api/app/routers/{menu,categories,items}.py.
 * The /api/menu response shape matches Grab's actual API (loose dict), so
 * consumers should treat it as `unknown` until they parse the categories/items
 * out of it.
 */

export type MenuPayload = Record<string, unknown>;

export interface MenuResponse {
  menu: MenuPayload;
}

export interface CreateCategoryInput {
  name: string;
}

export interface CreateCategoryResult {
  category_id: string;
  name: string;
}

export interface SortCategoryItem {
  resource_id: string;
  sort_order: number;
}

export interface SortCategoryInput {
  items: SortCategoryItem[];
}

export interface CreateItemInput {
  name: string;
  description?: string;
  price_vnd: number;
  category_id: string;
  image_urls?: string[];
  linked_modifier_group_ids?: string[];
}

export interface CreateItemResult {
  item_id: string;
  item_name: string;
}

export interface UploadImageResult {
  url: string;
}

const MENU_KEY = ["menu"] as const;

async function fetchMenu(): Promise<MenuPayload> {
  const res = await api.get<MenuResponse>("/api/menu");
  return res.menu;
}

async function createCategory(input: CreateCategoryInput): Promise<CreateCategoryResult> {
  return api.post<CreateCategoryResult>("/api/categories", input);
}

async function deleteCategory(id: string): Promise<{ deleted: boolean }> {
  return api.delete<{ deleted: boolean }>(`/api/categories/${encodeURIComponent(id)}`);
}

async function sortCategories(input: SortCategoryInput): Promise<{ success: boolean }> {
  return api.put<{ success: boolean }>("/api/categories/sort", input);
}

async function createItem(input: CreateItemInput): Promise<CreateItemResult> {
  return api.post<CreateItemResult>("/api/items", input);
}

/**
 * Multipart upload for a menu-item image. The backend stores the file
 * temporarily and forwards it to Grab; we receive the hosted URL.
 */
async function uploadImage(file: File): Promise<UploadImageResult> {
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch(`${apiBase()}/api/items/upload-image`, {
    method: "POST",
    credentials: "include",
    body: fd,
  });
  const text = await res.text();
  if (!res.ok) {
    throw new ApiError(res.status, text || `HTTP ${res.status}`, text);
  }
  return JSON.parse(text) as UploadImageResult;
}

function apiBase(): string {
  // Mirror `apps/web/lib/api.ts`: in dev we use the Next.js rewrite
  // (relative URLs) so the browser hits its own origin and avoids CORS.
  if (process.env.NODE_ENV !== "production") return "";
  return process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8124";
}

export function useMenu() {
  return useQuery({
    queryKey: MENU_KEY,
    queryFn: fetchMenu,
    staleTime: 30_000,
  });
}

export function useCreateCategory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: createCategory,
    onSuccess: () => qc.invalidateQueries({ queryKey: MENU_KEY }),
  });
}

export function useDeleteCategory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: deleteCategory,
    onSuccess: () => qc.invalidateQueries({ queryKey: MENU_KEY }),
  });
}

export function useSortCategories() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: sortCategories,
    onSuccess: () => qc.invalidateQueries({ queryKey: MENU_KEY }),
  });
}

export function useCreateItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: createItem,
    onSuccess: () => qc.invalidateQueries({ queryKey: MENU_KEY }),
  });
}

export function useUploadItemImage() {
  return useMutation({
    mutationFn: uploadImage,
  });
}

export { MENU_KEY };
