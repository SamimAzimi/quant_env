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
  probs?: {
    p_up: number;
    up: Record<string, number>;    // "0.5","1.0","1.5","2.0" -> P(r > mu+kσ)
    down: Record<string, number>;  // P(r < mu-kσ)
  };
  hist?: { edges: number[]; counts: number[] };
}
export interface CleanSegment {
  from: number;
  to: number;
  n: number;
  eff_mean: number | null;
  adverse_mean: number | null;
  bars_mean: number | null;
}
export interface SideStats {
  bands: number[];
  n: number;
  p_breakout: (number | null)[];
  p_touch: (number | null)[];
  breakout_counts: number[];
  matrix: (number | null)[][];     // [breakout band][target band]
  clean_segments: CleanSegment[];
}
export interface Trigger {
  key: string;
  label: string;
  overnight: boolean;
  n_days: number;
  up: SideStats;
  down: SideStats;
}
export interface Reference {
  key: string;
  label: string;
  reference_dist: DistStats;
  triggers: Trigger[];
}
export interface AssetStatsReport {
  asset: string;
  timeframe: string;
  n_bars: number;
  n_days: number;
  date_range: [string, string];
  available_range: [string, string];
  bands: number[];
  sessions: Record<string, DistStats>;
  references: Reference[];
}
export interface AssetRange { start: string; end: string; n_days: number }

// --- band-behaviour study ---
export interface BandTest {
  name: string; null: string; statistic: number | null;
  p_value: number | null; crit_5pct?: number; reject_5pct?: boolean;
  interpretation: string;
}
export interface BandRow {
  band: number; touch_rate: number | null; median_touch: number | null;
  survival: number[]; n_touch: number;
  candles_to_touch_mean: number | null; adverse_bands_mean: number | null;
  oscillation_mean: number | null; candles_inside_mean: number | null;
  depth_mean: number | null;
}
export interface EscapeRow {
  band: number; n_exits: number; mean_signed_bands: number | null;
  mean_abs_bands: number | null; toward_center_share: number | null;
}
export interface BandPair {
  analyze: string; trigger: string; note?: string;
  n_days?: number; n_candles?: number;
  A?: { counts: number[]; probs: number[]; expected_probs: number[] };
  B_C?: BandRow[];
  D?: { matrix: number[][]; toward_center: (number | null)[] };
  E?: EscapeRow[];
  F?: BandTest[];
  G?: { bullets: string[]; verdict: string; n_tests: number; n_rejections: number };
}
export interface BandStudy {
  asset: string; timeframe: string; date_range: [string, string];
  band_step: number; band_max: number; band_labels: string[];
  pairs: BandPair[];
}
export interface SavedReportMeta {
  id: number; kind: string; title: string; params: Record<string, unknown>;
  created_at: string;
}

// --- strategy reports ---
export interface RunSummary {
  run_id: string; asset: string; strategy: string; timeframe: string;
  asset_class: string; saved_at: string; n_trades: number;
  headline: Record<string, number | string | null>;
}
export interface RunReport {
  run_id: string; asset: string; strategy: string; timeframe: string;
  asset_class: string; saved_at: string; n_trades: number;
  metadata: Record<string, unknown>;
  metrics: Record<string, number | string | null>;
  equity: { step: number; time: string | null; equity: number }[];
  frames: Record<string, { columns: string[]; data: unknown[][] }>;
}
export interface RunTrades {
  total: number; offset: number;
  rows: {
    trade_id: string; side: string | null; entry_time: string | null;
    exit_time: string | null; entry_price: number | null;
    exit_price: number | null; exit_reason: string | null;
    net_pnl: number | null; r_multiple: number | null;
    equity_after: number | null; extra: Record<string, unknown>;
  }[];
}

// --- day-over-day + quant character ---
export interface DayToDayState {
  key: string; label: string; n: number;
  p_next_up?: number; p_next_gt_1sd?: number; p_next_lt_1sd?: number; mean_next?: number;
}
export interface Performance {
  note?: string;
  n_days?: number; ann_return?: number; ann_vol?: number;
  sharpe?: number | null; sortino?: number | null; calmar?: number | null;
  max_drawdown?: number; max_dd_duration_days?: number; current_drawdown?: number;
  var_95?: number; cvar_95?: number; var_99?: number; cvar_99?: number;
  win_rate?: number; avg_win?: number | null; avg_loss?: number | null;
  profit_factor?: number | null; omega_0?: number | null; tail_ratio?: number | null;
  best_day?: number; worst_day?: number; pct_positive?: number; skew?: number;
}
export interface QuantCharacter {
  note?: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  [k: string]: any;
}
export interface QuantStatsReport {
  asset: string; timeframe: string; n_bars: number; n_days: number;
  date_range: [string, string]; available_range: [string, string]; bands: number[];
  daily_distribution: DistStats;
  intraday_continuation: { note?: string; n_days?: number; up?: SideStats; down?: SideStats };
  day_to_day: DayToDayState[];
  gaps: { note?: string; dist?: DistStats; p_gap_up?: number;
    fill_prob_up?: number; fill_prob_down?: number;
    continue_up?: number; continue_down?: number };
  streaks: { note?: string; p_up?: number; p_up_given_up?: number;
    p_up_given_2up?: number; longest_up?: number; longest_down?: number };
  performance: Performance;
  character: QuantCharacter;
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
