import { useEffect, useState } from 'react';
import {
  api, withParams,
  type AssetCategory, type NewsItem, type RateProbHistory, type Reading,
  type Tag, type Trade,
} from '../api';
import MultiLineChart, { type LineData } from '../components/MultiLineChart';
import { SERIES_COLORS } from '../components/ReturnsChart';

const isoDaysAgo = (days: number) => {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString().slice(0, 10);
};

const fmt = (iso: string | null) =>
  iso ? `${iso.slice(0, 16).replace('T', ' ')} UTC` : '—';

const toPoints = (readings: Reading[]) =>
  readings.map((r) => ({
    time: Math.floor(new Date(`${r.ts}Z`).getTime() / 1000),
    value: r.value,
  }));

export default function HistoryPage() {
  const [start, setStart] = useState(isoDaysAgo(30));
  const [end, setEnd] = useState(isoDaysAgo(0));
  const range = { start, end };

  const [trades, setTrades] = useState<Trade[]>([]);
  const [news, setNews] = useState<NewsItem[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [categories, setCategories] = useState<AssetCategory[]>([]);
  const [tagFilter, setTagFilter] = useState('');
  const [effectFilter, setEffectFilter] = useState('');
  const [vix, setVix] = useState<Reading[]>([]);
  const [rateHist, setRateHist] = useState<RateProbHistory | null>(null);

  useEffect(() => {
    api.get<Tag[]>('/api/tags').then(setTags).catch(() => {});
    api.get<AssetCategory[]>('/api/effects').then(setCategories).catch(() => {});
  }, []);

  useEffect(() => {
    api.get<Trade[]>(withParams('/api/trades/history', range))
      .then(setTrades).catch(() => {});
    api.get<Reading[]>(withParams('/api/vix/history', range))
      .then(setVix).catch(() => {});
    api.get<RateProbHistory>(withParams('/api/rate-probs/history', range))
      .then(setRateHist).catch(() => {});
  }, [start, end]);

  useEffect(() => {
    api.get<NewsItem[]>(withParams('/api/news/history', {
      ...range, tag_id: tagFilter, effect_id: effectFilter,
    })).then(setNews).catch(() => {});
  }, [start, end, tagFilter, effectFilter]);

  const rateSeries: LineData[] = (rateHist?.buckets ?? []).map((bucket) => ({
    name: bucket,
    points: (rateHist?.series ?? [])
      .filter((s) => s.probs[bucket] != null)
      .map((s) => ({
        time: Math.floor(new Date(`${s.captured_at}Z`).getTime() / 1000),
        value: s.probs[bucket] as number,
      })),
  }));

  return (
    <main className="page">
      <div className="page-toolbar">
        <h1 className="page-title">History</h1>
        <label className="row small">
          <span className="muted">From</span>
          <input type="date" value={start} max={end} onChange={(e) => setStart(e.target.value)} />
        </label>
        <label className="row small">
          <span className="muted">To</span>
          <input type="date" value={end} min={start} max={isoDaysAgo(0)}
            onChange={(e) => setEnd(e.target.value)} />
        </label>
      </div>

      <div className="stats-grid">
        <div className="card span-2">
          <h2>History of trades</h2>
          {trades.length === 0 ? <p className="muted small">No trades in range.</p> : (
            <div style={{ overflowX: 'auto' }}>
              <table className="data">
                <thead>
                  <tr>
                    <th>Asset</th><th>Entry</th><th>Exit</th><th>Entry px</th>
                    <th>Exit px</th><th>TP</th><th>SL</th><th>Reasons</th>
                  </tr>
                </thead>
                <tbody>
                  {trades.map((t) => (
                    <tr key={t.id} className={t.exit_time ? '' : 'row-open'}>
                      <td>{t.asset?.ticker ?? '—'}</td>
                      <td>{fmt(t.entry_time)}</td>
                      <td>{t.exit_time ? fmt(t.exit_time) : <span className="chip open-chip">OPEN</span>}</td>
                      <td>{t.entry_price ?? '—'}</td>
                      <td>{t.exit_price ?? '—'}</td>
                      <td>{t.tp ?? '—'}</td>
                      <td>{t.sl ?? '—'}</td>
                      <td className="small muted">
                        {t.entry_reason}{t.exit_reason ? ` → ${t.exit_reason}` : ''}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="card span-2">
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <h2>History of news</h2>
            <div className="row">
              <select value={tagFilter} onChange={(e) => setTagFilter(e.target.value)}>
                <option value="">All tags</option>
                {tags.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
              </select>
              <select value={effectFilter} onChange={(e) => setEffectFilter(e.target.value)}>
                <option value="">All effects</option>
                {categories.map((c) => (
                  <optgroup key={c.id} label={c.name}>
                    {c.assets.map((a) => <option key={a.id} value={a.id}>{a.ticker}</option>)}
                  </optgroup>
                ))}
              </select>
            </div>
          </div>
          {news.length === 0 && <p className="muted small">No news in range.</p>}
          {news.map((n) => (
            <div key={n.id} className="news-item">
              <span className="small muted">{fmt(n.created_at)}</span>{' '}
              <span className="title">{n.title}</span>{' '}
              {n.effects.map((e) => <span key={e.id} className="chip effect">{e.ticker}</span>)}
              {n.tags.map((t) => <span key={t.id} className="chip tag">{t.name}</span>)}
              {n.body && <div className="small muted">{n.body}</div>}
            </div>
          ))}
        </div>

        <div className="card span-2">
          <h2>History of VIX change</h2>
          {vix.length < 2
            ? <p className="muted small">Not enough VIX readings in range.</p>
            : <MultiLineChart series={[{ name: 'VIX', points: toPoints(vix) }]} />}
        </div>

        <div className="card span-2">
          <h2>
            History of rate probabilities
            {rateHist?.meeting_date && (
              <span className="muted small"> — meeting {rateHist.meeting_date}</span>
            )}
          </h2>
          {rateSeries.length === 0 || (rateHist?.series.length ?? 0) < 2 ? (
            <p className="muted small">
              Record the FOMC table on multiple days to see the evolution.
            </p>
          ) : (
            <>
              <MultiLineChart series={rateSeries} suffix="%" />
              <div className="row small" style={{ marginTop: 6 }}>
                {rateSeries.map((s, i) => (
                  <span key={s.name}>
                    <span className="legend-dot"
                      style={{ background: SERIES_COLORS[i % SERIES_COLORS.length] }} />
                    {s.name} bps
                  </span>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </main>
  );
}
