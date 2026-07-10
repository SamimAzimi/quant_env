import { useEffect, useState } from 'react';
import {
  api, withParams,
  type RateProbHistory, type Reading, type Trade,
} from '../api';
import MultiLineChart, { type LineData } from '../components/MultiLineChart';
import { SERIES_COLORS } from '../components/ReturnsChart';
import NewsHistorySection from '../sections/NewsHistorySection';

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

interface StatsMeta {
  available: string[];
  default_charts: string[];
  timeframes: string[];
}

export default function HistoryPage() {
  const [start, setStart] = useState(isoDaysAgo(30));
  const [end, setEnd] = useState(isoDaysAgo(0));
  const range = { start, end };

  const [meta, setMeta] = useState<StatsMeta>({
    available: [], default_charts: [], timeframes: ['15m'],
  });
  const [trades, setTrades] = useState<Trade[]>([]);
  const [vix, setVix] = useState<Reading[]>([]);
  const [rateHist, setRateHist] = useState<RateProbHistory | null>(null);

  useEffect(() => {
    api.get<StatsMeta>('/api/stats/assets').then(setMeta).catch(() => {});
  }, []);

  useEffect(() => {
    api.get<Trade[]>(withParams('/api/trades/history', range))
      .then(setTrades).catch(() => {});
    api.get<Reading[]>(withParams('/api/vix/history', range))
      .then(setVix).catch(() => {});
    api.get<RateProbHistory>(withParams('/api/rate-probs/history', range))
      .then(setRateHist).catch(() => {});
  }, [start, end]);

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

        <NewsHistorySection
          start={start}
          end={end}
          timeframes={meta.timeframes}
          chartAssets={meta.available.length > 0 ? meta.available : meta.default_charts}
        />

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
