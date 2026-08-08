import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

/**
 * Tạp Dề Vàng — Grab's merchant quality tier programme.
 *
 * Mirrors services/api/app/routers/tiers.py.
 * GET /api/golden-apron — the tier ladder, its conditions, and where the
 * store stands on each one.
 */

export interface TierThreshold {
  /** The number the requirement sentence asks for. `null` when unparsed. */
  value: number | null;
  /** `"min"` — must reach it. `"max"` — must stay under it. `""` unknown. */
  direction: string;
  /** Wire key `is_percent`. */
  is_percent: boolean;
}

export interface TierMetric {
  /** Grab's machine name, e.g. `total_order`. */
  metric: string;
  /** Grab's wording, e.g. "Số lượng đơn hàng". */
  label: string;
  /** Grab's wording for the condition, e.g. "Đạt ít nhất 50". */
  requirement: string;
  threshold: TierThreshold;
  /** Grab's own verdict. Authoritative — never recomputed from `current`. */
  achieved: boolean;
  /**
   * Where the store stands. `null` when no Grab service could say —
   * `missing_or_wrong_items` and `score_completion_score` really do come
   * back empty. Render "chưa rõ", never 0: on a metric where lower is
   * better, a 0 reads as a perfect record.
   */
  current: number | null;
  /** Wire key `currentDisplay` — the figure as Grab sent it. */
  currentDisplay: string;
}

export interface TierLevel {
  /** "Cơ Bản" / "Bạc" / "Vàng". */
  name: string;
  metrics: TierMetric[];
  /** Wire key `isCurrent`. */
  isCurrent: boolean;
  /** Wire key `achievedCount`. */
  achievedCount: number;
  /** Wire key `totalCount`. */
  totalCount: number;
}

export interface GoldenApronStatus {
  /** Wire key `currentTierRaw` — Grab's English name, e.g. "Basic". */
  currentTierRaw: string;
  /** Wire key `currentTier` — the Vietnamese name. */
  currentTier: string;
  /** Wire key `isFirstMonth`. */
  isFirstMonth: boolean;
  levels: TierLevel[];
  rating: number | null;
  /** Wire key `ratingCount`. */
  ratingCount: number | null;
  /** Wire key `periodStart` / `periodEnd` — Grab measures per month. */
  periodStart: string;
  periodEnd: string;
  warnings: string[];
}

/**
 * The three figures the dashboard header shows.
 *
 * A cheap sibling of the full ladder — the tier page plus two small
 * reads, never the nine-request goals fan-out, because the header
 * renders a tier name and a star count and none of those numbers.
 */
export interface GoldenApronSummary {
  /** Wire key `currentTier` — "Cơ Bản" / "Bạc" / "Vàng". */
  currentTier: string;
  /** Wire key `apronTitle` — "Tạp Dề Cơ Bản". Empty when the tier is unknown. */
  apronTitle: string;
  rating: number | null;
  /** Wire key `ratingCount`. */
  ratingCount: number | null;
  /** Wire key `achievedCount` / `totalCount` — progress on the current tier. */
  achievedCount: number;
  totalCount: number;
  /**
   * Wire key `profileScore` — store-profile completeness, 0–100.
   * **Not** a star rating; the header used to render it as "100.0 / 5".
   */
  profileScore: number | null;
  /** Wire key `profileDesc` — Grab's sentence about that score. */
  profileDesc: string;
  warnings: string[];
}

const GOLDEN_APRON_KEY = ["golden-apron"] as const;
const GOLDEN_APRON_SUMMARY_KEY = ["golden-apron", "summary"] as const;

/**
 * Tier + stars for the dashboard header. Follows the tier as it moves:
 * the badge is derived from whatever Grab currently reports, never
 * stored, so a promotion shows up on the next refetch.
 */
export function useGoldenApronSummary(merchantId?: string | null) {
  return useQuery({
    // Keyed by store. The endpoint is scoped to the active-store cookie,
    // so without this a switch would leave the header showing the
    // previous store's tier and badge for the whole staleTime — beside a
    // merchant id that had already changed.
    queryKey: [...GOLDEN_APRON_SUMMARY_KEY, merchantId ?? null] as const,
    queryFn: () => api.get<GoldenApronSummary>("/api/golden-apron/summary"),
    enabled: merchantId !== undefined,
    staleTime: 10 * 60_000,
  });
}

/**
 * Ten-ish Grab round-trips behind one call, so it is cached for a while:
 * tier standing moves over days, and the metrics are recomputed monthly.
 */
export function useGoldenApron(merchantId?: string | null) {
  return useQuery({
    // Store-keyed for the same reason as the summary — see below.
    queryKey: [...GOLDEN_APRON_KEY, merchantId ?? null] as const,
    queryFn: () => api.get<GoldenApronStatus>("/api/golden-apron"),
    staleTime: 10 * 60_000,
  });
}

export { GOLDEN_APRON_KEY, GOLDEN_APRON_SUMMARY_KEY };
