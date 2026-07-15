import { useEffect, useState } from 'react';
import {
  api, withParams, type AssetRange, type AssetStatsReport,
} from '../api';
import DistHistogram from '../components/DistHistogram';
import TriggerCard from '../components/TriggerCard';

interface StatsMeta {
  available: string[];
  default_charts: string[];
  timeframes: string[];
}

/** Statistics of an asset: session/overlap distributions and conditional
 *  band-transition behaviour over a chosen date range. */
export default function AssetStatsPage() {
  const [meta, setMeta] = useState<StatsMeta>({
    available: [], default_charts: [], timeframes: ['15m'],
  });
  const [asset, setAsset] = useState('');
  const [tf, setTf] = useState('15m');
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [range, setRange] = useState<AssetRange | null>(null);
  const [report, setReport] = useState<AssetStatsReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    api.get<StatsMeta>('/api/stats/assets').then((m) => {
      setMeta(m);
      setAsset(m.available[0] ?? m.default_charts[0] ?? '');
    }).catch(() => {});
  }, []);

  // when asset/timeframe change, fetch the available range and default to full
  useEffect(() => {
    if (!asset) return;
    setRange(null); setReport(null); setError('');
    api.get<AssetRange>(withParams('/api/asset-stats/range', { asset, tf }))
      .then((r) => { setRange(r); setStart(r.start); setEnd(r.end); })
      .catch((e) => setError(String(e)));
  }, [asset, tf]);

  const run = () => {
    if (!asset) return;
    // omit start/end when they equal the full range (analyze full history)
    const full = range && start === range.start && end === range.end;
    setLoading(true); setError(''); setReport(null);
    api.get<AssetStatsReport>(withParams('/api/asset-stats', {
      asset, tf, start: full ? '' : start, end: full ? '' : end,
    }))
      .then(setReport)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  };

  const assetChoices = meta.available.length > 0 ? meta.available : meta.default_charts;

  return (
    <main className="page">
      <div className="page-toolbar">
        <h1 className="page-title">Statistics of an asset</h1>
        <label className="row small">
          <span className="muted">Ticker</span>
          <select value={asset} onChange={(e) => setAsset(e.target.value)}>
            {assetChoices.map((a) => <option key={a}>{a}</option>)}
          </select>
        </label>
        <label className="row small">
          <span className="muted">Timeframe</span>
          <select value={tf} onChange={(e) => setTf(e.target.value)}>
            {meta.timeframes.map((t) => <option key={t}>{t}</option>)}
          </select>
        </label>
        <label className="row small">
          <span className="muted">From</span>
          <input type="date" value={start} min={range?.start} max={end}
            onChange={(e) => setStart(e.target.value)} />
        </label>
        <label className="row small">
          <span className="muted">To</span>
          <input type="date" value={end} min={start} max={range?.end}
            onChange={(e) => setEnd(e.target.value)} />
        </label>
        <button className="primary" disabled={loading || !asset} onClick={run}>
          {loading ? 'Analyzing…' : 'Analyze'}
        </button>
      </div>

      {range && !report && !loading && (
        <p className="muted small">
          {asset} · {tf} — data available {range.start} → {range.end}
          ({range.n_days} days). The full range is used unless you narrow it.
          Press Analyze.
        </p>
      )}
      {error && <p className="error">{error}</p>}

      {report && (
        <>
          <p className="small muted">
            {report.asset} · {report.timeframe} · {report.n_days} days ·
            {report.date_range[0]} → {report.date_range[1]}. Bands: ±0.5/1/1.5/2σ.
          </p>

          <h2 className="section-head">Session &amp; overlap return distributions</h2>
          <div className="charts-grid">
            {Object.entries(report.sessions).map(([name, dist]) => (
              <DistHistogram key={name} dist={dist} title={name} />
            ))}
          </div>

          <h2 className="section-head">
            Conditional band transitions — every reference stacked
          </h2>
          <p className="small muted">
            Each reference session sets ±0.5/1/1.5/2σ bands from its own return
            distribution (anchored at its open). The matrix is
            P(touch <i>target</i>σ | trigger closes beyond <i>breakout</i>σ) —
            click a cell to select. Clean move is per adjacent segment:
            efficiency <code>|net|/Σ|bar move|</code>, mean adverse excursion
            (σ), bars, and sample count.
          </p>
          <div className="ref-stack">
            {report.references.map((ref) => (
              <div key={ref.key} className="card">
                <div className="row" style={{ justifyContent: 'space-between' }}>
                  <h2>{ref.label}</h2>
                  {ref.reference_dist.mean !== undefined && (
                    <span className="muted small">
                      ref μ {(ref.reference_dist.mean * 100).toFixed(2)}% ·
                      σ {((ref.reference_dist.std ?? 0) * 100).toFixed(2)}% ·
                      n={ref.reference_dist.n}
                    </span>
                  )}
                </div>
                {ref.triggers.length === 0 && (
                  <p className="muted small">Not enough reference data for bands.</p>
                )}
                {ref.triggers.map((trig) => (
                  <TriggerCard key={trig.key} trig={trig} />
                ))}
              </div>
            ))}
          </div>
        </>
      )}
    </main>
  );
}
