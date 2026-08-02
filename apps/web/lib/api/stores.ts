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

export { STORE_KEY };
