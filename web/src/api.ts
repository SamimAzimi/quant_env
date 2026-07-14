// Typed fetch helpers for the Market Preparation API.

export interface Tag { id: number; name: string }
export interface Asset { id: number; ticker: string; name: string }
export interface AssetCategory {
  id: number; name: string; kind: 'hard' | 'soft'; assets: Asset[];
}
export type NewsRole = 'primary' | 'supporting' | 'contradicting' | 'duplicate' | 'update';
export interface Source { id: number; name: string }
export interface NewsItem {
  id: number; title: string; body: string;
  role: NewsRole; status: 'open' | 'close';
  source: Source | null; publish_time: string;
  created_at: string; tags: Tag[]; effects: Asset[];
}
export interface NewsTree extends NewsItem { children: NewsTree[] }
export interface NewsThread {
  ancestors: NewsItem[];
  parent_ids: number[];
  tree: NewsTree;
}
export interface NewsGroup {
  name: string;
  news: NewsItem[];
  edges: [number, number][];
}
export interface Trade {
  id: number; asset_id: number | null; asset: Asset | null;
  entry_time: string; exit_time: string | null;
  entry_price: number | null; exit_price: number | null;
  entry_reason: string; exit_reason: string | null;
  tp: number | null; sl: number | null; remarks: string; created_at: string;
}
export interface Country { id: number; name: string }
export interface Reading { id: number; ts: string; value: number }
export interface Thought { id: number; ts: string; body: string }
export interface EconReport {
  id: number; name: string; country: Country | null;
  forecast: string; previous: string;
  actual: string | null; outcome: 'beat' | 'miss' | 'inline' | null;
  created_at: string;
}
export interface RateProbHistory {
  meeting_date: string | null;
  buckets: string[];
  series: { captured_at: string; probs: Record<string, number | null> }[];
}
export interface RateProb { meeting_date: string; bucket: string; probability: number }
export interface RateSnapshot { id: number; captured_at: string; probs: RateProb[] }
export interface Bar { time: number; open: number; high: number; low: number; close: number }
export interface Level { label: string; kind: string; value: number }
export interface SessionSpan { name: string; key: string; start: number; end: number }
export interface AssetChart {
  asset: string; timeframe: string; day: string;
  bars: Bar[]; levels: Level[]; sessions: SessionSpan[];
}
export interface ReturnsSeries {
  asset: string; day: string; points: { time: number; value: number }[];
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => '');
    throw new Error(`${res.status} ${res.statusText}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  get: <T>(url: string) => request<T>(url),
  post: <T>(url: string, body: unknown) =>
    request<T>(url, { method: 'POST', body: JSON.stringify(body) }),
  patch: <T>(url: string, body: unknown) =>
    request<T>(url, { method: 'PATCH', body: JSON.stringify(body) }),
  delete: async (url: string): Promise<void> => {
    const res = await fetch(url, { method: 'DELETE' });
    if (!res.ok) {
      throw new Error(`${res.status} ${res.statusText}: ${await res.text().catch(() => '')}`);
    }
  },
};

export interface AlertItem {
  id: number; due_time: string; message: string; created_at: string;
}

// --- asset statistics ---
export interface DistStats {
  n: number;
  note?: string;
  mean?: number;
  std?: number;
  skew?: number;
  bands?: { up1: number; up2: number; dn1: number; dn2: number };
  probs?: {
    p_up: number; p_gt_1sd: number; p_gt_2sd: number;
    p_lt_1sd: number; p_lt_2sd: number;
  };
  hist?: { edges: number[]; counts: number[] };
}
export interface CleanStats {
  n: number;
  eff_mean: number | null;
  eff_median: number | null;
  mae_sd_mean: number | null;
  bars_mean: number | null;
}
export interface SideStats {
  n_days: number;
  n_breakout: number;
  n_target: number;
  p_breakout: number | null;
  p_target: number | null;
  p_target_given_breakout: number | null;
  clean: CleanStats;
}
export interface Transition {
  reference: string;
  trigger: string;
  overnight: boolean;
  note?: string;
  ref_mean?: number;
  ref_std?: number;
  bands?: { up1: number; up2: number; dn1: number; dn2: number };
  up?: SideStats;
  down?: SideStats;
}
export interface DayToDay {
  n: number;
  p_next_up?: number;
  p_next_gt_1sd?: number;
  p_next_lt_1sd?: number;
  mean_next?: number;
}
export interface DailyStudy extends DistStats {
  intraday?: { up: SideStats; down: SideStats };
  day_to_day?: { after_up_1sd: DayToDay; after_down_1sd: DayToDay };
}
export interface AssetStatsReport {
  asset: string;
  timeframe: string;
  n_bars: number;
  n_days: number;
  date_range: [string, string];
  sessions: Record<string, DistStats>;
  transitions: Transition[];
  daily: DailyStudy;
}

const pad = (n: number) => String(n).padStart(2, '0');

/** Stored UTC ISO → value for a datetime-local input in the browser's zone. */
export function utcToLocalInput(iso: string): string {
  const d = new Date(iso.endsWith('Z') ? iso : `${iso}Z`);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** datetime-local value (browser's zone) → UTC ISO for the API. */
export function localInputToUtc(value: string): string {
  return new Date(value).toISOString();
}

/** Append query params, skipping empty values. */
export function withParams(url: string, params: Record<string, string>): string {
  const q = Object.entries(params)
    .filter(([, v]) => v !== '')
    .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
    .join('&');
  return q ? `${url}${url.includes('?') ? '&' : '?'}${q}` : url;
}
