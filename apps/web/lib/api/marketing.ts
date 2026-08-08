import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

/**
 * Marketing API surface.
 *
 * Mirrors services/api/app/routers/marketing.py.
 * GET /api/marketing — programs on offer + campaigns already joined.
 */

export interface SpotlightEvent {
  event_id: string;
  name: string;
  description: string;
  is_eligible: boolean;
  /** Empty when the payload carried nothing that looked like an image. */
  image_url: string;
  /** From the detail endpoint. `null` means the lookup was skipped or
   *  failed — show no funding note rather than guessing one. */
  is_grab_cofund: boolean | null;
  /** Best funding share across the program's tiers, 0–1. */
  max_grab_funded_pct: number | null;
  /** Grab's untouched row — the programs endpoint has no discount or
   *  co-funding figures, so anything extra it does send lives here. */
  raw: Record<string, unknown>;
}

export interface CampaignPerformance {
  marketing_spend: number;
  assisted_sales: number;
  assisted_orders: number;
  /** Grab's `ssmRoms`. 44.9 renders as "44.9x". */
  roms: number;
  /** False for a campaign that hasn't run — distinct from one that ran
   *  and returned zeros. */
  has_data: boolean;
}

/** Grab's own buckets, in the order the Merchant app lists them. */
export type CampaignStatus =
  | "evergreen"
  | "ongoing"
  | "upcoming"
  | "inReview"
  | "paused"
  | "past";

export interface MarketingCampaign {
  campaign_id: string;
  name: string;
  campaign_type: string;
  status: CampaignStatus | string;
  start_time: string;
  end_time: string;
  image_url: string;
  performance: CampaignPerformance;
  raw: Record<string, unknown>;
}

export interface MarketingCounts {
  in_review: number;
  upcoming: number;
  ongoing: number;
  evergreen: number;
  paused: number;
  past: number;
  total: number;
}

export interface MarketingOverviewResponse {
  events: SpotlightEvent[];
  campaigns: MarketingCampaign[];
  counts: MarketingCounts;
  /** One half failing doesn't blank the page — the reason lands here. */
  warnings: string[];
}

/** One condition line under a tier, kept exactly as Grab worded it. */
export interface PromoBullet {
  /** `"MOV"` = minimum order value, `"CO_FUND"` = Grab's share. */
  type: string;
  content: string;
}

/**
 * One discount option inside a program.
 *
 * Every money field is nullable on purpose: the figures are read out of
 * Vietnamese sentences, so "Grab didn't state this" has to stay distinct
 * from "Grab stated zero". Render `—`, never `0đ`, when a field is null.
 */
export interface PromoTier {
  /** e.g. "Giảm 12.000đ cho đơn hàng" — the source of `discount_vnd`. */
  title: string;
  category: string;
  /** Grab's row kind: `ORDER` (whole basket) or `ITEM` (selected dishes). */
  kind: string;
  /** Flat discounts only. Null on a percentage tier even when its title
   *  names a cap in đồng — a ceiling is not the amount. */
  discount_vnd: number | null;
  /** Set instead of `discount_vnd` for "giảm 50%" programs, whose cost
   *  depends on the item and can't be stated in đồng. */
  discount_percent: number | null;
  /** The "tối đa Yđ" ceiling on a percentage tier, kept separate so it
   *  is never mistaken for the discount. */
  discount_cap_vnd: number | null;
  min_order_vnd: number | null;
  grab_cofund_vnd: number | null;
  /** `discount − cofund`. What the store actually pays per order — the
   *  number that decides the program, and one Grab never shows. */
  merchant_cost_vnd: number | null;
  /** `cofund / discount`, 0–1. Observed 0.08–0.20, not the 0.5–0.8 the
   *  phrase "đồng tài trợ" suggests. */
  grab_funded_pct: number | null;
  /** Non-empty when the parsed figures contradict each other. Render it —
   *  it is the difference between a wrong number and a wrong number that
   *  looks right. */
  parse_note: string;
  bullets: PromoBullet[];
}

/**
 * Where a program advertises the store — not a discount tier.
 *
 * Grab lists these alongside the promo tiers, distinguished only by a
 * `*_AD` row type. They restate the headline discount but have no
 * co-funding split, so rendered as tiers they showed a "Grab ?%" badge
 * and three blank figures for something that has no share to fund.
 */
export interface AdPlacement {
  /** `CAROUSEL_AD`, `SEARCH_AD`, … */
  kind: string;
  title: string;
  subtitle: string;
}

export interface EventCostItem {
  title: string;
  /** Grab's own wording for the rate, e.g. "8%". Free text, not a number. */
  fee: string;
  notes: string[];
}

export interface EventScheduleItem {
  label: string;
  content: string;
  tags: string[];
}

/** Grab's join action, from the program page's footer section. */
export interface EventOptIn {
  /** Grab's own button label, e.g. "Tham gia chiến dịch". */
  cta: string;
  /** Terms sentence, markdown link included. */
  terms: string;
}

export interface SpotlightEventDetail {
  event_id: string;
  name: string;
  description: string;
  status: string;
  hero_image_url: string;
  /** The detail payload's raw `isEligible`. Do **not** render this as
   *  eligibility: verified against the live store, every offered program
   *  returns `false` here while the list says `true` and all of them show
   *  a working join button. Use `can_join`. */
  is_eligible: boolean;
  /** Grab included an OPT_IN action — the signal that actually tracks
   *  whether this store can join. */
  can_join: boolean;
  opt_in: EventOptIn | null;
  is_promo_stacking: boolean;
  /** `null` when Grab's payload never stated it. Check `=== false` before
   *  telling the operator Grab doesn't co-fund. */
  is_grab_cofund: boolean | null;
  tiers: PromoTier[];
  ad_placements: AdPlacement[];
  costs: EventCostItem[];
  schedule: EventScheduleItem[];
  /** Section types the backend didn't decode. Surfaced so unread terms
   *  never look like absent terms. */
  unknown_sections: string[];
  raw: Record<string, unknown>;
}

const MARKETING_KEY = ["marketing", "overview"] as const;

async function fetchMarketing(): Promise<MarketingOverviewResponse> {
  return api.get<MarketingOverviewResponse>("/api/marketing");
}

/**
 * Both halves in one call.
 *
 * No `refetchInterval`: this hits two Grab services per request and the
 * catalogue changes on the order of days, not seconds. The operator can
 * refresh by hand.
 */
export function useMarketing() {
  return useQuery({
    queryKey: MARKETING_KEY,
    queryFn: fetchMarketing,
    staleTime: 5 * 60_000,
  });
}

/**
 * Full terms for one program.
 *
 * Deliberately **not** folded into `useMarketing`. Each program costs its
 * own Grab round-trip, and a store can be offered a dozen; fetching them
 * all up front would stall the page on requests for programs the operator
 * never opens. `enabled` keeps it dormant until a card is actually opened.
 *
 * Cached longer than the overview — a program's terms are fixed for its
 * whole run, so refetching them is pure cost.
 */
export function useProgramDetail(eventId: string | null) {
  return useQuery({
    queryKey: ["marketing", "event", eventId] as const,
    queryFn: () =>
      api.get<SpotlightEventDetail>(
        `/api/marketing/events/${encodeURIComponent(eventId!)}`,
      ),
    enabled: Boolean(eventId),
    staleTime: 30 * 60_000,
  });
}

export { MARKETING_KEY };
