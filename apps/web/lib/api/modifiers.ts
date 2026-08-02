import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

/**
 * Modifier-group API surface.
 *
 * Mirrors services/api/app/routers/modifiers.py.
 * GET  /api/modifiers        - list every modifier group on the store
 * POST /api/modifiers/verify - pre-flight check
 * POST /api/modifiers/groups - create new group
 */

export interface ModifierSpec {
  name: string;
  name_en?: string;
  price_vnd: number;
}

export interface VerifyModifierInput extends ModifierSpec {}

/** A single modifier option inside a group (e.g. "Trân châu", "200g"). */
export interface ModifierOption {
  modifier_id: string;
  modifier_name: string;
  price_display?: string | null;
  price_vnd: number;
  is_need_extra_cost: boolean;
  available_status?: number | null;
  sort_order: number;
  quantity: number;
  max_modifier_selection_quantity?: number | null;
}

/** A group of related modifier options (e.g. "Topping", "Size"). */
export interface ModifierGroup {
  modifier_group_id: string;
  modifier_group_name: string;
  selection_range_min: number;
  selection_range_max: number;
  modifiers: ModifierOption[];
}

export interface CreateModifierGroupInput {
  group_name: string;
  selection_range_min?: number;
  selection_range_max?: number;
  modifiers?: ModifierSpec[];
}

export interface CreateModifierGroupResult {
  modifier_group_id: string;
  modifier_group_name: string;
}

const MODIFIER_GROUPS_KEY = ["modifier-groups"] as const;

async function listModifierGroups(): Promise<ModifierGroup[]> {
  const res = await api.get<{ modifier_groups: ModifierGroup[]; total: number }>(
    "/api/modifiers"
  );
  return res.modifier_groups ?? [];
}

async function verifyModifier(input: VerifyModifierInput): Promise<{ ok: true }> {
  return api.post<{ ok: true }>("/api/modifiers/verify", input);
}

async function createModifierGroup(input: CreateModifierGroupInput): Promise<CreateModifierGroupResult> {
  return api.post<CreateModifierGroupResult>("/api/modifiers/groups", input);
}

/** Pull every modifier group attached to the active store. */
export function useModifierGroups() {
  return useQuery({
    queryKey: MODIFIER_GROUPS_KEY,
    queryFn: listModifierGroups,
    staleTime: 30_000,
  });
}

export function useVerifyModifier() {
  return useMutation({ mutationFn: verifyModifier });
}

export function useCreateModifierGroup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: createModifierGroup,
    onSuccess: () => qc.invalidateQueries({ queryKey: MODIFIER_GROUPS_KEY }),
  });
}

export { MODIFIER_GROUPS_KEY };
