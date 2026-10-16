// Shapes returned by the FastAPI service (src/avant_offre/api/app.py).

export type Band = "GO" | "REVIEW" | "NO-GO";

export interface Explanation {
  uid: string | null;
  objet: string;
  notified_on: string | null;
  similarity: number;
}

export interface ShortlistItem {
  notice_id: string;
  rank: number;
  fit_percentile: number;
  band: Band;
  total: number | null;
  deadline_on: string | null;
  published_on: string | null;
  buyer_name: string | null;
  objet: string | null;
  dept: string | null;
  url: string | null;
  explanations: Explanation[];
}

export interface Excluded {
  notice_id: string;
  objet: string | null;
  deadline_on: string | null;
  reasons: string[];
  labels: string[];
}

export interface Shortlist {
  company_key: string | null;
  week_start: string;
  week_end: string;
  eligible: ShortlistItem[];
  excluded: Excluded[];
}

export interface Tender {
  notice_id: string;
  buyer_name: string | null;
  objet: string | null;
  published_on: string | null;
  deadline_on: string | null;
  dept: string | null;
  cpv: string | null;
  procedure: string | null;
  estimated_value_eur: number | null;
  url: string | null;
}

export interface Stat {
  value: number | null;
  n: number;
  sources: string[];
  note: string | null;
}

export interface Competitor {
  public_id: string;
  name: string;
  score: number;
  comparable_wins: number;
  last_win_on: string | null;
  incumbent_with_buyer: boolean;
  new_to_buyer: boolean;
  sources: string[];
}

export interface PriceRange {
  p10: number | null;
  p25: number | null;
  p50: number | null;
  p75: number | null;
  p90: number | null;
  n: number;
  sources: string[];
  note: string | null;
}

export interface MarketIntel {
  n_comparables: number;
  competitors: Competitor[];
  newcomer_share: Stat;
  price_range: PriceRange;
  sme_share: Stat;
  bids_received: Stat;
  buyer_top_winner_share: Stat;
  company_references: Stat | null;
}

export interface Criterion {
  id: string;
  label: string;
  weight: number;
  value: number | null;
  input: number | null;
  assessed: boolean;
  note: string | null;
}

export interface Score {
  total: number | null;
  band: Band;
  criteria: Criterion[];
  not_assessed: string[];
  assessed_weight: number;
  hard_stops: string[];
}

export interface Fact {
  id: string;
  key: string;
  label: string;
  display: string;
  sources: string[];
}

export interface Brief {
  brief_id: string;
  text: string;
  model: string | null;
  fallback: boolean;
  fallback_reason: string | null;
  removed: { section: string; sentence: string; reason: string }[];
  facts: Fact[];
}

export interface Award {
  uid: string;
  notified_on: string | null;
  buyer_name: string | null;
  objet: string | null;
  amount_eur: number | null;
  is_framework: boolean;
  winners: string[] | null;
}
