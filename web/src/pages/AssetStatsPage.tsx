import { useEffect, useState } from 'react';
import {
  api, withParams, type AssetRange, type AssetStatsReport, type BandStudy,
  type SavedReportMeta,
} from '../api';
import BandStudyCard from '../components/BandStudyCard';
import DistHistogram from '../components/DistHistogram';

interface StatsMeta {
  available: string[];
  default_charts: string[];
  timeframes: string[];
}

/** Statistics of an asset: session/overlap distributions plus the
 *  band-behaviour study for each consecutive session pair. */
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
  const [bands, setBands] = useState<BandStudy | null>(null);
  const [saved, setSaved] = useState<SavedReportMeta[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [msg, setMsg] = useState('');

  useEffect(() => {
    api.get<StatsMeta>('/api/stats/assets').then((m) => {
      setMeta(m);
      setAsset(m.available[0] ?? m.default_charts[0] ?? '');
    }).catch(() => {});
    loadSaved();
  }, []);

  const loadSaved = () =>
    api.get<SavedReportMeta[]>('/api/saved-reports?kind=band_study')
      .then(setSaved).catch(() => {});

  useEffect(() => {
    if (!asset) return;
    setRange(null); setReport(null); setBands(null); setError('');
    api.get<AssetRange>(withParams('/api/asset-stats/range', { asset, tf }))
      .then((r) => { setRange(r); setStart(r.start); setEnd(r.end); })
      .catch((e) => setError(String(e)));
  }, [asset, tf]);

  const run = () => {
    if (!asset) return;
    const full = range && start === range.start && end === range.end;
    const p = { asset, tf, start: full ? '' : start, end: full ? '' : end };
    setLoading(true); setError(''); setReport(null); setBands(null); setMsg('');
    Promise.all([
      api.get<AssetStatsReport>(withParams('/api/asset-stats', p)),
      api.get<BandStudy>(withParams('/api/asset-stats/bands', p)),
    ])
      .then(([r, b]) => { setReport(r); setBands(b); })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  };

  const saveStudy = async () => {
    if (!bands) return;
    const title = `${bands.asset} ${bands.timeframe} band study ` +
      `${bands.date_range[0]}→${bands.date_range[1]}`;
    await api.post('/api/saved-reports', {
      kind: 'band_study', title,
      params: { asset, tf, start, end },
      payload: bands,
    });
    setMsg('Saved ✓');
    loadSaved();
  };

  const copyStudy = async () => {
    if (!bands) return;
    await navigator.clipboard.writeText(JSON.stringify(bands));
    setMsg('Copied JSON to clipboard — paste into any AI prompt');
  };

  const loadStudy = async (id: number) => {
    const r = await api.get<{ payload: BandStudy }>(`/api/saved-reports/${id}`);
    setBands(r.payload);
    setReport(null);
    setMsg('Loaded saved study');
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

      {range && !report && !bands && !loading && (
        <p className="muted small">
          {asset} · {tf} — data available {range.start} → {range.end}
          ({range.n_days} days). Full range used unless narrowed. Press Analyze.
        </p>
      )}
      {saved.length > 0 && (
        <p className="small muted">
          Saved studies:{' '}
          {saved.map((s) => (
            <button key={s.id} className="ghost small" onClick={() => loadStudy(s.id)}>
              {s.title}
            </button>
          ))}
        </p>
      )}
      {error && <p className="error">{error}</p>}
      {msg && <p className="small">{msg}</p>}

      {report && (
        <>
          <h2 className="section-head">Session &amp; overlap return distributions
            <span className="muted"> — {report.timeframe} closes</span>
          </h2>
          <div className="charts-grid">
            {Object.entries(report.sessions).map(([name, dist]) => (
              <DistHistogram key={name} dist={dist} title={name} />
            ))}
          </div>
        </>
      )}

      {bands && (
        <>
          <div className="row" style={{ justifyContent: 'space-between', marginTop: 18 }}>
            <h2 className="section-head" style={{ margin: 0 }}>
              Band behaviour — {bands.asset} · {bands.timeframe} ·
              0.25σ bands to ±4σ · {bands.date_range[0]} → {bands.date_range[1]}
            </h2>
            <span className="row">
              <button className="ghost small" onClick={saveStudy}>💾 Save report</button>
              <button className="ghost small" onClick={copyStudy}>⧉ Copy for AI prompt</button>
            </span>
          </div>
          <p className="small muted">
            For each pair: where the next session's {bands.timeframe} closes land
            in the previous session's bands, how fast each band is first touched
            (survival curves), the path's shape, the band→band transition matrix,
            escape velocity, and whether it all beats noise.
          </p>
          <div className="ref-stack">
            {bands.pairs.map((p) => (
              <BandStudyCard key={`${p.analyze}-${p.trigger}`} pair={p}
                labels={bands.band_labels} />
            ))}
          </div>
        </>
      )}
    </main>
  );
}
