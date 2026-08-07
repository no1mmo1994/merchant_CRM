import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

/**
 * Modifier-group API surface.
 *
 * Mirrors services/api/app/routers/modifiers.py.
 * GET    /api/modifiers                  - list every modifier group on the store
 * POST   /api/modifiers/verify           - pre-flight check
 * POST   /api/modifiers/groups           - create new group
 * PUT    /api/modifiers/groups/{id}      - edit an existing group
 * DELETE /api/modifiers/groups/{id}      - remove a group
 */

export interface ModifierSpec {
  name: string;
  name_en?: string;
  price_vnd: number;
  /**
   * Grab's id for an option that already exists. Omit for a new option.
   * On edit this must be echoed back for every option kept, otherwise
   * Grab drops and recreates them under new ids.
   */
  modifier_id?: string;
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

/** One category link for a modifier group. A group can be re-used
 * across categories (e.g. "Topping" attached to every drink), so each
 * link records `(category_id, category_name, item_count)` — the UI
 * sums to render "Liên kết với N món" and lists each category. */
export interface ModifierGroupCategoryLink {
  category_id: string;
  category_name: string;
  item_count: number;
}

/** A group of related modifier options (e.g. "Topping", "Size"). */
export interface ModifierGroup {
  modifier_group_id: string;
  modifier_group_name: string;
  selection_range_min: number;
  selection_range_max: number;
  modifiers: ModifierOption[];
  /** How many menu items currently reference this group ("Liên kết với X món"). */
  linked_item_count?: number;
  /** Per-category breakdown — replaces the previous "Nguồn: menu_fallback"
   *  badge with "Thuộc: <CategoryName> (<CategoryID>) · N món". */
  linked_categories?: ModifierGroupCategoryLink[];
}

/**
 * Backend's `/api/modifiers` payload. `partial: true` indicates the
 * list came from the menu-fallback path (Grab's authoritative
 * `/menu/modifier-groups` was unreachable) — the UI can show an info
 * hint but the data is still usable.
 */
export interface ListModifierGroupsResponse {
  modifier_groups: ModifierGroup[];
  total: number;
  partial: boolean;
  source: "direct" | "menu_fallback" | "empty";
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

/**
 * Body for editing an existing group.
 *
 * `modifiers` is a full replacement of the group's options, not a delta.
 * Every option the operator kept MUST carry its original `modifier_id`
 * (see `ModifierSpec.modifier_id`) — dropping it makes Grab recreate the
 * option under a fresh id, which breaks anything already pointing at the
 * old one. New options leave it unset.
 */
export interface UpdateModifierGroupInput {
  group_name: string;
  selection_range_min?: number;
  selection_range_max?: number;
  modifiers?: ModifierSpec[];
}

export interface UpdateModifierGroupResult {
  modifier_group_id: string;
  modifier_group_name: string;
  /**
   * False when the server saved the change but could not confirm Grab
   * edited in place rather than creating a duplicate — the group listing
   * was unreadable, or the before/after snapshots came from different
   * Grab surfaces. The edit itself went through; only the duplicate
   * check was skipped, so the UI should say so instead of a plain
   * success.
   */
  verified?: boolean;
}

export interface DeleteModifierGroupResult {
  modifier_group_id: string;
  deleted: boolean;
}

/**
 * The full set of menu items that should offer a group — a desired end
 * state, not a delta. Items left out get unlinked, so the picker can be
 * a plain checkbox list and the server works out the difference.
 */
export interface SetGroupItemsInput {
  item_ids: string[];
}

export interface SetGroupItemsResult {
  modifier_group_id: string;
  linked: string[];
  unlinked: string[];
  /** Already in the requested state; no request was made for these. */
  unchanged: string[];
  /** `{item_id: reason}` for items Grab rejected. Partial success is normal. */
  failed: Record<string, string>;
  /**
   * False when Grab refused the menu edit lock. The writes were still
   * attempted, but conflicts are likelier — worth surfacing rather than
   * letting a 409 look inexplicable.
   */
  lock_acquired: boolean;
}

const MODIFIER_GROUPS_KEY = ["modifier-groups"] as const;

async function listModifierGroups(): Promise<ModifierGroup[]> {
  const res = await api.get<ListModifierGroupsResponse>("/api/modifiers");
  return res.modifier_groups ?? [];
}

/** Side-channel: read the raw payload (including `partial` flag). */
export async function listModifierGroupsRaw(): Promise<ListModifierGroupsResponse> {
  return api.get<ListModifierGroupsResponse>("/api/modifiers");
}

async function verifyModifier(input: VerifyModifierInput): Promise<{ ok: true }> {
  return api.post<{ ok: true }>("/api/modifiers/verify", input);
}

async function createModifierGroup(input: CreateModifierGroupInput): Promise<CreateModifierGroupResult> {
  return api.post<CreateModifierGroupResult>("/api/modifiers/groups", input);
}

async function updateModifierGroup(
  groupId: string,
  input: UpdateModifierGroupInput,
): Promise<UpdateModifierGroupResult> {
  return api.put<UpdateModifierGroupResult>(
    `/api/modifiers/groups/${encodeURIComponent(groupId)}`,
    input,
  );
}

async function setGroupItems(
  groupId: string,
  input: SetGroupItemsInput,
): Promise<SetGroupItemsResult> {
  return api.put<SetGroupItemsResult>(
    `/api/modifiers/groups/${encodeURIComponent(groupId)}/items`,
    input,
  );
}

async function deleteModifierGroup(groupId: string): Promise<DeleteModifierGroupResult> {
  return api.delete<DeleteModifierGroupResult>(
    `/api/modifiers/groups/${encodeURIComponent(groupId)}`,
  );
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

/**
 * Edit an existing group.
 *
 * NOTE for callers: invalidating `MODIFIER_GROUPS_KEY` is not enough to
 * refresh the /modifiers page. That page deliberately bypasses this
 * query — it needs the `partial` / `source` fields that
 * `useModifierGroups` discards — and keeps its own `reload()`. Call that
 * too, the way `ModifierEditor` does via `onCreated`. The invalidation
 * below still matters for any other consumer of the query.
 */
export function useUpdateModifierGroup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ groupId, input }: { groupId: string; input: UpdateModifierGroupInput }) =>
      updateModifierGroup(groupId, input),
    onSuccess: () => qc.invalidateQueries({ queryKey: MODIFIER_GROUPS_KEY }),
  });
}

/** Delete a group. See `useUpdateModifierGroup` on refreshing the page. */
export function useDeleteModifierGroup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: deleteModifierGroup,
    onSuccess: () => qc.invalidateQueries({ queryKey: MODIFIER_GROUPS_KEY }),
  });
}

/**
 * Set which menu items offer a group. Invalidates the menu too — link
 * state lives on the items, so a stale menu would show the old picture.
 * As with the other mutations here, the /modifiers page keeps its own
 * reload() and needs calling separately.
 */
export function useSetGroupItems() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ groupId, input }: { groupId: string; input: SetGroupItemsInput }) =>
      setGroupItems(groupId, input),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: MODIFIER_GROUPS_KEY });
      void qc.invalidateQueries({ queryKey: ["menu"] });
    },
  });
}

export { MODIFIER_GROUPS_KEY };
