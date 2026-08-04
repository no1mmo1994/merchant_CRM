import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

/**
 * Stores list + detail API surface. Mirrors services/api/app/routers/stores.py.
 */

export interface StoreSummary {
  id: number;
  merchant_id: string;
  name: string;
  address: string;
  last_refresh_at: string | null;
  created_at: string;
}

export interface StoreListResponse {
  stores: StoreSummary[];
}

export interface StoreDetailResponse {
  store: StoreSummary;
  business_attributes: Record<string, unknown>;
  scorecard: Record<string, unknown>;
}

/**
 * Combined Grab store info / payout / scorecard payload returned by
 * `GET /api/stores/{merchant_id}/info`. Each section is wrapped in
 * `{ok, data, error}` so the UI can render the other two sections when
 * Grab is partial.
 */
export interface StoreInfoSection<T> {
  ok: boolean;
  data: T;
  error: string | null;
}

export interface StoreInfoData {
  name: string | null;
  address: string | null;
  status: string | null;
  email: string | null;
  latitude: number | null;
  longitude: number | null;
  photo: string | null;
  small_picture: string | null;
}

export interface PayoutData {
  store_phone: string | null;
  owner_name: string | null;
  owner_phone: string | null;
  bank_account_name: string | null;
  bank_name: string | null;
  bank_account_number: string | null;
}

export interface ScorecardData {
  title: string | null;
  desc: string | null;
  score: number | null;
  scoreRank: string | null;
  raw: Record<string, unknown>;
}

export interface StoreInfoResponse {
  store: StoreSummary;
  store_info: StoreInfoSection<StoreInfoData>;
  payout: StoreInfoSection<PayoutData>;
  scorecard: StoreInfoSection<ScorecardData>;
  business_attributes: StoreInfoSection<Record<string, unknown>>;
}

export interface AuthnTokenReveal {
  merchant_id: string;
  authn_token: string;
  last_refresh_at: string | null;
}

export interface StoreStatusData {
  ok: boolean;
  error: string | null;
  status: string | null;
  status_display: string | null;
  pending: boolean | null;
  raw: Record<string, unknown>;
}

/**
 * Live store name + `isOpen` flag + 7-day opening-hours table.
 *
 * Mirrors `cuahang/trangthai.py` which calls
 * `GET https://api.grab.com/food/merchant/v2/merchants`. The backend
 * projects the raw Grab envelope into this small schema at
 * `GET /api/stores/{merchant_id}/opening-hours`.
 *
 * `day_index` matches Grab's array order (0 = Monday ... 6 = Sunday).
 * `ranges` may be empty (`[]`) when the store is closed all day.
 */
export interface OpeningHourRange {
  start: string;
  end: string;
}

export interface OpeningHourDay {
  day_index: number;
  ranges: OpeningHourRange[];
}

export interface OpeningHoursData {
  name: string | null;
  is_open: boolean | null;
  /** Realtime runtime state from `GET /food/merchant/v3/open-status`.
   * Three valid values: "Open" (NORMAL), "BusyMode" (BẬN — still
   * accepting orders with longer prep), "Paused" (TEMPPAUSED —
   * not accepting orders). `null` when the v3 endpoint failed and
   * we lost the label. Mirrors `cuahang/trangthai2.py`. */
  status_label?: "Open" | "BusyMode" | "Paused" | null;
  /** Verbatim human label from Grab (e.g. "Quán đang bận", "Đang mở
   * cửa", "Đang tạm nghỉ, mở lại lúc 21:00"). The merchant app
   * shows this exact string on the home screen — we surface it
   * verbatim so the dashboard reflects exactly what the operator
   * sees in the app. */
  status_content?: string | null;
  /** Operator-friendly sentence the UI renders under the pill,
   * e.g. "Cửa hàng đang tạm nghỉ · Đang tạm nghỉ, mở lại lúc 21:00".
   * Synthesized by the backend — combines label + content. */
  status_note?: string | null;
  opening_hours: OpeningHourDay[];
}

export interface OpeningHoursResponse {
  ok: boolean;
  data: OpeningHoursData;
  error: string | null;
}

/**
 * `kind` discriminator for the store-status update endpoint
 * (`POST /api/stores/{merchant_id}/status`). Maps to Grab's
 * `PUT /food/merchant/v1/merchant/status` with different payloads:
 *  - "temp_pause" → NORMAL ↔ TEMPPAUSED (mirrors cuahang/setting_timecuahang.py)
 *  - "busy"       → NORMAL ↔ BUSY       (mirrors cuahang/sêtting_busy.py)
 */
export type StoreStatusKind = "temp_pause" | "busy";

export interface UpdateStoreStatusInput {
  kind: StoreStatusKind;
  /** When true, exit the current paused/busy state → NORMAL. */
  unpause?: boolean;
  /** Required for kind="temp_pause" + unpause=false. UTC ISO-8601. */
  pause_end_utc?: string | null;
  /** Required for kind="busy" + unpause=false. One of 15, 30, 60. */
  minutes?: 15 | 30 | 60 | null;
  /**
   * Live runtime state the dashboard read from
   * `GET /food/merchant/v3/open-status` (same source as
   * `OpeningHoursData.status_label`). The backend uses it to pick the
   * correct `fromState` for Grab's
   * `PUT /food/merchant/v1/merchant/status` — without this the
   * dashboard was always sending `fromState: "NORMAL"` and Grab 409'd
   * the request the moment the store was actually in BUSY /
   * TEMPPAUSED. Falsy values fall back to "NORMAL" on the server side
   * (preserving the old behaviour for any external API consumer).
   */
  current_runtime?: "Open" | "BusyMode" | "Paused" | null;
}

export interface UpdateStoreStatusResult {
  merchant_id: string;
  kind: StoreStatusKind;
  unpause: boolean;
  raw: Record<string, unknown>;
}

const STORE_KEY = ["stores"] as const;
const STORE_DETAIL_KEY = (merchantId: string) => ["stores", "detail", merchantId] as const;
const STORE_INFO_KEY = (merchantId: string) => ["stores", "info", merchantId] as const;

async function fetchStores(): Promise<StoreSummary[]> {
  const res = await api.get<StoreListResponse>("/api/stores");
  return res.stores;
}

async function fetchStore(merchantId: string): Promise<StoreDetailResponse> {
  return api.get<StoreDetailResponse>(`/api/stores/${encodeURIComponent(merchantId)}`);
}

async function fetchStoreInfo(merchantId: string): Promise<StoreInfoResponse> {
  return api.get<StoreInfoResponse>(`/api/stores/${encodeURIComponent(merchantId)}/info`);
}

async function revealAuthnToken(merchantId: string): Promise<AuthnTokenReveal> {
  return api.get<AuthnTokenReveal>(`/api/stores/${encodeURIComponent(merchantId)}/authn-token`);
}

async function fetchStoreStatus(merchantId: string): Promise<StoreStatusData> {
  return api.get<StoreStatusData>(
    `/api/stores/${encodeURIComponent(merchantId)}/status`
  );
}

async function fetchStoreOpeningHours(merchantId: string): Promise<OpeningHoursResponse> {
  return api.get<OpeningHoursResponse>(
    `/api/stores/${encodeURIComponent(merchantId)}/opening-hours`
  );
}

async function updateStoreStatus(
  merchantId: string,
  input: UpdateStoreStatusInput,
): Promise<UpdateStoreStatusResult> {
  return api.post<UpdateStoreStatusResult>(
    `/api/stores/${encodeURIComponent(merchantId)}/status`,
    input,
  );
}

async function selectStore(merchantId: string): Promise<{ ok: true }> {
  return api.post<{ ok: true }>("/api/stores/select", { merchant_id: merchantId });
}

export function useStores() {
  return useQuery({
    queryKey: STORE_KEY,
    queryFn: fetchStores,
    staleTime: 60_000,
  });
}

export function useStore(merchantId: string | null) {
  return useQuery({
    queryKey: merchantId ? STORE_DETAIL_KEY(merchantId) : ["stores", "detail", "_none"],
    queryFn: () => fetchStore(merchantId as string),
    enabled: Boolean(merchantId),
    staleTime: 30_000,
  });
}

/**
 * Live store info / payout / scorecard for the Settings page + Dashboard
 * scorecard tile. Refreshed on every store switch (invalidation key
 * includes the merchant id).
 */
export function useStoreInfo(merchantId: string | null) {
  return useQuery({
    queryKey: merchantId ? STORE_INFO_KEY(merchantId) : ["stores", "info", "_none"],
    queryFn: () => fetchStoreInfo(merchantId as string),
    enabled: Boolean(merchantId),
    staleTime: 60_000,
  });
}

/**
 * Lazy reveal of the decrypted authnToken — only fired when the Settings
 * page actually clicks "Show authn token". Each call writes an
 * `audit_log` row server-side.
 */
export function useRevealAuthnToken() {
  return useMutation({
    mutationFn: (merchantId: string) => revealAuthnToken(merchantId),
  });
}

export function useSelectStore() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: selectStore,
    onSuccess: () => qc.invalidateQueries({ queryKey: STORE_KEY }),
  });
}

export function useStoreStatus(merchantId: string | null) {
  return useQuery({
    queryKey: merchantId
      ? ["stores", "status", merchantId]
      : ["stores", "status", "_none"],
    queryFn: () => fetchStoreStatus(merchantId as string),
    enabled: Boolean(merchantId),
    staleTime: 30_000,
    // Poll every 30s so the topbar "Đang hoạt động" / "Lỗi AuthToken"
    // pill reflects live reality (the user reported it was stuck on
    // "active" forever, even when the local token was stale).
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
  });
}

/**
 * Live merchant `isOpen` + 7-day operating-hours table.
 *
 * Mirror of `cuahang/trangthai.py`. Same 30s polling cadence as
 * `useStoreStatus` so the overview card refreshes in lockstep with
 * the active-store pill — no extra fetches per render.
 */
export function useStoreOpeningHours(merchantId: string | null) {
  return useQuery({
    queryKey: merchantId
      ? ["stores", "opening-hours", merchantId]
      : ["stores", "opening-hours", "_none"],
    queryFn: () => fetchStoreOpeningHours(merchantId as string),
    enabled: Boolean(merchantId),
    staleTime: 30_000,
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
  });
}

/**
 * POST /api/stores/{merchant_id}/status — toggle TEMPPAUSED / BUSY.
 *
 * On success:
 *   1. Optimistically patches the cached `useStoreOpeningHours()` query
 *      so the overview pill (`Open` / `BusyMode` / `Paused`) flips
 *      instantly — no waiting for the 30 s poll. The next poll will
 *      reconcile with Grab's truth.
 *   2. Invalidates `useStoreStatus()` and `useStoreInfo()` so the
 *      account-level cards refresh within the polling tick.
 *
 * Mapping `kind + unpause` → resulting runtime label + boolean:
 *   - temp_pause + !unpause → label="Paused",   is_open=false (TEMPPAUSED)
 *   - temp_pause + unpause  → label="Open",     is_open=true  (NORMAL)
 *   - busy       + !unpause → label="BusyMode", is_open=true  (BUSY, still open)
 *   - busy       + unpause  → label="Open",     is_open=true  (NORMAL)
 *
 * Why BUSY ≠ closed: Grab's `merchant.isOpen` (and the v3/open-status
 * `statusLabel`) reflect whether the store is accepting orders; BUSY
 * mode is "accepting with longer prep times". Only `Paused` flips
 * `is_open` to false. Mirrors `cuahang/trangthai2.py`'s enum logic.
 */
export function useUpdateStoreStatus(merchantId: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: UpdateStoreStatusInput) =>
      updateStoreStatus(merchantId as string, input),
    onSuccess: (_data, input) => {
      // 1) Optimistic patch — flip the pill the moment the request
      //    returns 2xx, instead of waiting up to 30 s for the next poll.
      if (merchantId) {
        const hoursKey = ["stores", "opening-hours", merchantId];
        const prev = qc.getQueryData<OpeningHoursResponse>(hoursKey);
        if (prev) {
          const projected = computeResultingState(input);
          qc.setQueryData<OpeningHoursResponse>(hoursKey, {
            ...prev,
            data: {
              ...prev.data,
              is_open: projected.is_open,
              status_label: projected.status_label,
              // Best-effort operator note. The real `status_content`
              // will land on the next poll (we don't compute the
              // human label client-side — Grab's wording differs by
              // merchant app version).
              status_note: projected.status_note,
            },
          });
        }
      }

      // 2) Background invalidation so a stale poll comes back fresh and
      //    reconciles any drift between our optimistic guess and Grab.
      if (merchantId) {
        qc.invalidateQueries({ queryKey: ["stores", "status", merchantId] });
      }
      // The /info payload may also include state — invalidate to be safe.
      if (merchantId) {
        qc.invalidateQueries({ queryKey: ["stores", "info", merchantId] });
      }
      // Re-fetch opening hours so the optimistic patch is replaced
      // with the real Grab response (and the 7-day schedule stays
      // authoritative — we never patch `opening_hours` optimistically).
      if (merchantId) {
        qc.invalidateQueries({
          queryKey: ["stores", "opening-hours", merchantId],
        });
      }
    },
  });
}

/**
 * Resolve the resulting pill state for the dashboard based on the
 * request we just dispatched. See `useUpdateStoreStatus` for the
 * mapping rationale.
 */
function computeResultingState(input: UpdateStoreStatusInput): {
  status_label: OpeningHoursData["status_label"];
  is_open: boolean | null;
  status_note: string | null;
} {
  if (input.unpause) {
    return {
      status_label: "Open",
      is_open: true,
      status_note: "Cửa hàng đang mở cửa",
    };
  }
  if (input.kind === "temp_pause") {
    return {
      status_label: "Paused",
      is_open: false,
      status_note: "Cửa hàng đang tạm nghỉ",
    };
  }
  if (input.kind === "busy") {
    return {
      status_label: "BusyMode",
      is_open: true,
      status_note: "Quán đang bận",
    };
  }
  return {
    status_label: null,
    is_open: null,
    status_note: null,
  };
}

export { STORE_KEY };
