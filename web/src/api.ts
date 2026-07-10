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
export interface AssetChart {
  asset: string; timeframe: string; day: string; bars: Bar[]; levels: Level[];
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
};

/** Append query params, skipping empty values. */
export function withParams(url: string, params: Record<string, string>): string {
  const q = Object.entries(params)
    .filter(([, v]) => v !== '')
    .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
    .join('&');
  return q ? `${url}${url.includes('?') ? '&' : '?'}${q}` : url;
}
