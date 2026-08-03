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

export interface UpdateItemInput {
  name?: string;
  description?: string;
  name_en?: string;
  description_en?: string;
  price_vnd?: number;
  category_id?: string;
  image_urls?: string[];
  linked_modifier_group_ids?: string[];
  selling_time_id?: string;
}

export interface UpdateItemResult {
  item_id: string;
  item_name: string;
  available?: boolean | null;
}

export interface UpdateAvailabilityInput {
  /** Bật/tắt đơn giản — backend map sang status=1 (true) / 3 (false). */
  available?: boolean;
  /** Lý do cụ thể (khớp Grab's v1 endpoint enum):
   *  1 = AVAILABLE (bật, cần selling_time_id)
   *  2 = OUT_OF_STOCK_TODAY (hết bán hôm nay)
   *  3 = OUT_OF_STOCK (vẫn hiển thị nhưng không order được)
   */
  status?: 1 | 2 | 3;
  /** Bắt buộc khi status=1 (server sẽ tự fetch nếu thiếu). */
  selling_time_id?: string;
  /** Ẩn hoàn toàn khỏi menu khách (eligibleSellingStatus=INELIGIBLE).
   *  Khác với status=3 — item không hiển thị với khách, merchant vẫn edit được.
   */
  hidden?: boolean;
}

export interface UpdateAvailabilityResult {
  item_id: string;
  available?: boolean | null;
  status?: number | null;
  hidden?: boolean | null;
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

async function updateItem(itemId: string, input: UpdateItemInput): Promise<UpdateItemResult> {
  return api.put<UpdateItemResult>(`/api/items/${encodeURIComponent(itemId)}`, input);
}

async function updateItemAvailability(
  itemId: string,
  input: UpdateAvailabilityInput,
): Promise<UpdateAvailabilityResult> {
  return api.patch<UpdateAvailabilityResult>(
    `/api/items/${encodeURIComponent(itemId)}/availability`,
    input,
  );
}

/**
 * Multipart upload for a menu-item image. The backend stores the file
 * temporarily and forwards it to Grab; we receive the hosted URL.
 *
 * Error envelope from the backend looks like
 *   { detail: { code: "grab_rejected_upload", message: "...", grab_status: 409, ... } }
 * — we want `message` (not raw JSON) to reach `toast.error()`.
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
    let parsed: unknown = text;
    if (text && res.headers.get("content-type")?.includes("application/json")) {
      try {
        parsed = JSON.parse(text);
      } catch {
        /* leave parsed = text */
      }
    }
    let message = `HTTP ${res.status}`;
    if (parsed && typeof parsed === "object" && "detail" in parsed) {
      const detail = (parsed as { detail: unknown }).detail;
      if (detail && typeof detail === "object" && !Array.isArray(detail)) {
        const d = detail as Record<string, unknown>;
        if (typeof d.message === "string" && d.message) message = d.message;
        else if (typeof d.code === "string" && d.code) message = d.code;
      } else if (typeof detail === "string" && detail.trim()) {
        message = detail.trim();
      }
    } else if (text) {
      message = text;
    }
    throw new ApiError(res.status, message, parsed);
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

export function useUpdateItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ itemId, input }: { itemId: string; input: UpdateItemInput }) =>
      updateItem(itemId, input),
    onSuccess: () => qc.invalidateQueries({ queryKey: MENU_KEY }),
  });
}

export function useUpdateItemAvailability() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ itemId, input }: { itemId: string; input: UpdateAvailabilityInput }) =>
      updateItemAvailability(itemId, input),
    // Optimistic toggle so the Switch feels instant. On error we roll back
    // and let the consumer show the toast.
    onMutate: async ({ itemId, input }) => {
      await qc.cancelQueries({ queryKey: MENU_KEY });
      const prev = qc.getQueryData<MenuPayload>(MENU_KEY);
      if (prev && typeof prev === "object") {
        // Derive optimistic `available` flag from whichever field the caller
        // supplied. status=1 means ON; status=2/3 mean OFF; `available`
        // maps directly. `hidden` doesn't change `available` but flips
        // `eligibleSellingStatus`.
        const optimisticAvailable =
          typeof input.status === "number"
            ? input.status === 1
            : typeof input.available === "boolean"
            ? input.available
            : undefined;
        qc.setQueryData<MenuPayload>(
          MENU_KEY,
          toggleAvailability(prev, itemId, {
            available: optimisticAvailable,
            hidden: input.hidden,
          }),
        );
      }
      return { prev };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.prev) qc.setQueryData(MENU_KEY, ctx.prev);
    },
    onSettled: () => qc.invalidateQueries({ queryKey: MENU_KEY }),
  });
}

/**
 * Walk the cached menu and flip availableStatus + eligibleSellingStatus
 * on the matching item. Both are optional — pass only the field you want
 * to change.
 */
function toggleAvailability(
  menu: MenuPayload,
  itemId: string,
  patch: { available?: boolean; hidden?: boolean },
): MenuPayload {
  const categories = (menu as { categories?: unknown }).categories;
  if (!Array.isArray(categories)) return menu;
  const next = categories.map((cat) => {
    if (!cat || typeof cat !== "object") return cat;
    const items = (cat as { items?: unknown }).items;
    if (!Array.isArray(items)) return cat;
    return {
      ...(cat as Record<string, unknown>),
      items: items.map((it) => {
        if (!it || typeof it !== "object") return it;
        const rec = it as Record<string, unknown>;
        const id = rec.itemID ?? rec.skuID ?? rec.id;
        if (String(id ?? "") !== itemId) return it;
        const updated: Record<string, unknown> = { ...rec };
        if (typeof patch.available === "boolean") {
          updated.availableStatus = patch.available ? "AVAILABLE" : "OUT_OF_STOCK";
        }
        if (typeof patch.hidden === "boolean") {
          updated.eligibleSellingStatus = patch.hidden ? "INELIGIBLE" : "ELIGIBLE";
        }
        return updated;
      }),
    };
  });
  return { ...(menu as Record<string, unknown>), categories: next };
}

export function useUploadItemImage() {
  return useMutation({
    mutationFn: uploadImage,
  });
}

export { MENU_KEY };
