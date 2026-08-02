import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

/**
 * Settings API surface — token refresh, audit log, danger-zone delete.
 */

export interface AuditLogEntry {
  id: number;
  action: string;
  entity_type: string;
  entity_id: string;
  payload_json: string;
  created_at: string;
}

export interface AuditLogListResponse {
  entries: AuditLogEntry[];
  total: number;
}

export interface RefreshTokenInput {
  merchant_id: string;
}

export interface RefreshTokenResult {
  ok: true;
  refreshed_at: string;
}

async function refreshToken(input: RefreshTokenInput): Promise<RefreshTokenResult> {
  return api.post<RefreshTokenResult>("/api/auth/refresh-token", input);
}

async function fetchAuditLog(limit = 50, offset = 0): Promise<AuditLogListResponse> {
  return api.get<AuditLogListResponse>(
    `/api/audit?limit=${limit}&offset=${offset}`
  );
}

async function deleteStore(merchantId: string): Promise<{ deleted: true }> {
  return api.delete<{ deleted: true }>(`/api/stores/${encodeURIComponent(merchantId)}`);
}

export function useRefreshToken() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: refreshToken,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["auth"] });
      qc.invalidateQueries({ queryKey: ["stores"] });
    },
  });
}

export function useAuditLog(limit = 50, offset = 0) {
  return useQuery({
    queryKey: ["audit", limit, offset],
    queryFn: () => fetchAuditLog(limit, offset),
    staleTime: 30_000,
  });
}

export function useDeleteStore() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: deleteStore,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["stores"] });
      qc.invalidateQueries({ queryKey: ["audit"] });
    },
  });
}
