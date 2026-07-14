import { useEffect, useState } from 'react';
import { api, withParams, type AssetStatsReport, type DayToDay } from '../api';
import DistHistogram from '../components/DistHistogram';
import TransitionCard from '../components/TransitionCard';

interface StatsMeta {
  available: string[];
  default_charts: string[];
  timeframes: string[];
}

const pctOrDash = (x: number | null | undefined) =>
  x === null || x === undefined ? '—' : `${(x * 100).toFixed(1)}%`;

function DayCond({ label, d }: { label: string; d: DayToDay }) {
  return (
    <div className="news-item">
      <div className="small" style={{ fontWeight: 600 }}>{label} <span className="muted">n={d.n}</span></div>
      {d.n > 0 ? (
        <div className="small muted">
          next day up {pctOrDash(d.p_next_up)} · &gt;+1σ {pctOrDash(d.p_next_gt_1sd)} ·
          &lt;−1σ {pctOrDash(d.p_next_lt_1sd)} · mean {((d.mean_next ?? 0) * 100).toFixed(2)}%
        </div>
      ) : <div className="small muted">no occurrences</div>}
    </div>
  );
}

/** Statistics of an asset: session-transition and day-over-day behaviour. */
export default function AssetStatsPage() {
  const [meta, setMeta] = useState<StatsMeta>({
    available: [], default_charts: [], timeframes: ['15m'],
  });
  const [asset, setAsset] = useState('');
  const [tf, setTf] = useState('15m');
  const [report, setReport] = useState<AssetStatsReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    api.get<StatsMeta>('/api/stats/assets').then((m) => {
      setMeta(m);
      const first = m.available[0] ?? m.default_charts[0] ?? '';
      setAsset(first);
    }).catch(() => {});
  }, []);

  const run = () => {
    if (!asset) return;
    setLoading(true); setError(''); setReport(null);
    api.get<AssetStatsReport>(withParams('/api/asset-stats', { asset, tf }))
      .then(setReport)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  };

  const assetChoices = meta.available.length > 0 ? meta.available : meta.default_charts;
  const daily = report?.daily;

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
        <button className="primary" disabled={loading || !asset} onClick={run}>
          {loading ? 'Analyzing…' : 'Analyze'}
        </button>
      </div>

      {error && <p className="error">{error}</p>}
      {!report && !error && !loading && (
        <p className="muted">
          Pick a ticker and an intraday timeframe, then Analyze. The backend
          studies every trading day of history: session log-return
          distributions (Tokyo, London, New York), how cleanly one session's
          breakout continues to the next session's 2σ, and the same
          conditional statistics day-over-day.
        </p>
      )}

      {report && (
        <>
          <p className="small muted">
            {report.asset} · {report.timeframe} · {report.n_days} days ·
            {report.date_range[0]} → {report.date_range[1]}
          </p>

          <h2 className="section-head">Session return distributions</h2>
          <div className="charts-grid">
            {Object.entries(report.sessions).map(([name, dist]) => (
              <DistHistogram key={name} dist={dist} title={name} />
            ))}
            {daily && <DistHistogram dist={daily} title="Full trading day" />}
          </div>

          <h2 className="section-head">Session transitions — conditional continuation</h2>
          <div className="stats-grid">
            {report.transitions.map((t) => (
              <TransitionCard key={`${t.reference}-${t.trigger}`} t={t} />
            ))}
          </div>

          {daily && (
            <>
              <h2 className="section-head">Day-over-day</h2>
              <div className="stats-grid">
                <div className="card">
                  <h2>Intraday continuation</h2>
                  <p className="small muted">
                    Anchored at the day open, using the daily return μ/σ bands.
                  </p>
                  {daily.intraday && (
                    <div className="row" style={{ gap: 18, alignItems: 'flex-start' }}>
                      <div style={{ flex: 1, minWidth: 220 }}>
                        <div className="small" style={{ fontWeight: 600 }}>▲ Upside</div>
                        <div className="small muted">
                          P(close&gt;+1σ) {pctOrDash(daily.intraday.up.p_breakout)}<br />
                          P(+2σ | breakout) {pctOrDash(daily.intraday.up.p_target_given_breakout)}<br />
                          clean eff {daily.intraday.up.clean.eff_mean !== null
                            ? `${(daily.intraday.up.clean.eff_mean * 100).toFixed(0)}%` : '—'}
                        </div>
                      </div>
                      <div style={{ flex: 1, minWidth: 220 }}>
                        <div className="small" style={{ fontWeight: 600 }}>▼ Downside</div>
                        <div className="small muted">
                          P(close&lt;−1σ) {pctOrDash(daily.intraday.down.p_breakout)}<br />
                          P(−2σ | breakout) {pctOrDash(daily.intraday.down.p_target_given_breakout)}<br />
                          clean eff {daily.intraday.down.clean.eff_mean !== null
                            ? `${(daily.intraday.down.clean.eff_mean * 100).toFixed(0)}%` : '—'}
                        </div>
                      </div>
                    </div>
                  )}
                </div>
                <div className="card">
                  <h2>Day-to-day conditional</h2>
                  <p className="small muted">Given the previous day closed beyond ±1σ.</p>
                  {daily.day_to_day && (
                    <>
                      <DayCond label="After an up day (&gt;+1σ)" d={daily.day_to_day.after_up_1sd} />
                      <DayCond label="After a down day (&lt;−1σ)" d={daily.day_to_day.after_down_1sd} />
                    </>
                  )}
                </div>
              </div>
            </>
          )}
        </>
      )}
    </main>
  );
}
