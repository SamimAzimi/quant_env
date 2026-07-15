import { useEffect, useState } from 'react';
import {
  api, withParams, type AssetRange, type QuantStatsReport,
} from '../api';
import DistHistogram from '../components/DistHistogram';
import TriggerCard from '../components/TriggerCard';

interface StatsMeta { available: string[]; default_charts: string[]; timeframes: string[] }

const pc = (x: number | null | undefined, d = 1) =>
  x === null || x === undefined ? '—' : `${(x * 100).toFixed(d)}%`;
const num = (x: number | null | undefined, d = 2) =>
  x === null || x === undefined ? '—' : x.toFixed(d);

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="stat-tile">
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
      {hint && <div className="stat-hint muted">{hint}</div>}
    </div>
  );
}

function KV({ rows }: { rows: [string, string][] }) {
  return (
    <table className="data">
      <tbody>
        {rows.map(([k, v]) => (
          <tr key={k}><th className="muted">{k}</th><td>{v}</td></tr>
        ))}
      </tbody>
    </table>
  );
}

export default function DayStatsPage() {
  const [meta, setMeta] = useState<StatsMeta>({ available: [], default_charts: [], timeframes: ['15m'] });
  const [asset, setAsset] = useState('');
  const [tf, setTf] = useState('1h');
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [range, setRange] = useState<AssetRange | null>(null);
  const [report, setReport] = useState<QuantStatsReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    api.get<StatsMeta>('/api/stats/assets').then((m) => {
      setMeta(m);
      setAsset(m.available[0] ?? m.default_charts[0] ?? '');
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (!asset) return;
    setRange(null); setReport(null); setError('');
    api.get<AssetRange>(withParams('/api/quant-stats/range', { asset, tf }))
      .then((r) => { setRange(r); setStart(r.start); setEnd(r.end); })
      .catch((e) => setError(String(e)));
  }, [asset, tf]);

  const run = () => {
    if (!asset) return;
    const full = range && start === range.start && end === range.end;
    setLoading(true); setError(''); setReport(null);
    api.get<QuantStatsReport>(withParams('/api/quant-stats', {
      asset, tf, start: full ? '' : start, end: full ? '' : end,
    })).then(setReport).catch((e) => setError(String(e))).finally(() => setLoading(false));
  };

  const assetChoices = meta.available.length > 0 ? meta.available : meta.default_charts;
  const p = report?.performance;
  const ch = report?.character;
  const ic = report?.intraday_continuation;

  return (
    <main className="page">
      <div className="page-toolbar">
        <h1 className="page-title">Day &amp; Quant Stats</h1>
        <label className="row small"><span className="muted">Ticker</span>
          <select value={asset} onChange={(e) => setAsset(e.target.value)}>
            {assetChoices.map((a) => <option key={a}>{a}</option>)}
          </select>
        </label>
        <label className="row small"><span className="muted">Timeframe</span>
          <select value={tf} onChange={(e) => setTf(e.target.value)}>
            {meta.timeframes.map((t) => <option key={t}>{t}</option>)}
          </select>
        </label>
        <label className="row small"><span className="muted">From</span>
          <input type="date" value={start} min={range?.start} max={end}
            onChange={(e) => setStart(e.target.value)} />
        </label>
        <label className="row small"><span className="muted">To</span>
          <input type="date" value={end} min={start} max={range?.end}
            onChange={(e) => setEnd(e.target.value)} />
        </label>
        <button className="primary" disabled={loading || !asset} onClick={run}>
          {loading ? 'Analyzing…' : 'Analyze'}
        </button>
      </div>

      {range && !report && !loading && (
        <p className="muted small">{asset} · {tf} — {range.start} → {range.end}
          ({range.n_days} days). Press Analyze.</p>
      )}
      {error && <p className="error">{error}</p>}

      {report && p && !p.note && (
        <>
          <h2 className="section-head">Performance &amp; risk (daily)</h2>
          <div className="tile-grid">
            <Tile label="Ann. return" value={pc(p.ann_return)} />
            <Tile label="Ann. vol" value={pc(p.ann_vol)} />
            <Tile label="Sharpe" value={num(p.sharpe)} />
            <Tile label="Sortino" value={num(p.sortino)} />
            <Tile label="Calmar" value={num(p.calmar)} />
            <Tile label="Max drawdown" value={pc(p.max_drawdown)} hint={`${p.max_dd_duration_days}d, now ${pc(p.current_drawdown)}`} />
            <Tile label="VaR 95 / 99" value={`${pc(p.var_95, 2)} / ${pc(p.var_99, 2)}`} hint="daily loss" />
            <Tile label="CVaR 95 / 99" value={`${pc(p.cvar_95, 2)} / ${pc(p.cvar_99, 2)}`} hint="tail avg" />
            <Tile label="Win rate" value={pc(p.win_rate)} hint={`avg +${pc(p.avg_win, 2)} / ${pc(p.avg_loss, 2)}`} />
            <Tile label="Profit factor" value={num(p.profit_factor)} />
            <Tile label="Tail ratio" value={num(p.tail_ratio)} hint="p95/p05" />
            <Tile label="Best / worst" value={`${pc(p.best_day, 1)} / ${pc(p.worst_day, 1)}`} />
          </div>

          <h2 className="section-head">Daily return distribution &amp; intraday continuation</h2>
          <div className="stats-grid">
            <div className="card">
              <h2>Daily return</h2>
              <DistHistogram dist={report.daily_distribution} title="ln(day close / day open)" />
            </div>
            <div className="card span-2">
              <h2>Intraday continuation</h2>
              <p className="small muted">Anchored at the day open, using the daily σ-bands.</p>
              {ic && !ic.note && ic.up && ic.down ? (
                <TriggerCard trig={{ key: 'day', label: 'Rest of the day', overnight: false,
                  n_days: ic.n_days ?? 0, up: ic.up, down: ic.down }} />
              ) : <p className="muted small">{ic?.note ?? 'No data.'}</p>}
            </div>
          </div>

          <h2 className="section-head">Day-to-day, gaps &amp; streaks</h2>
          <div className="stats-grid">
            <div className="card">
              <h2>Day-to-day transition</h2>
              <p className="small muted">Given the previous day's σ-bucket → next day.</p>
              <table className="data">
                <thead><tr><th>Prev day</th><th>n</th><th>next up</th><th>&gt;+1σ</th><th>&lt;−1σ</th><th>mean</th></tr></thead>
                <tbody>
                  {report.day_to_day.map((s) => (
                    <tr key={s.key}>
                      <td>{s.label}</td><td>{s.n}</td>
                      <td>{pc(s.p_next_up, 0)}</td><td>{pc(s.p_next_gt_1sd, 0)}</td>
                      <td>{pc(s.p_next_lt_1sd, 0)}</td><td>{pc(s.mean_next, 2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="card">
              <h2>Overnight gaps</h2>
              {report.gaps.note ? <p className="muted small">{report.gaps.note}</p> : (
                <KV rows={[
                  ['Gap up freq', pc(report.gaps.p_gap_up, 0)],
                  ['Fill prob (gap up)', pc(report.gaps.fill_prob_up, 0)],
                  ['Fill prob (gap down)', pc(report.gaps.fill_prob_down, 0)],
                  ['Continue up | gap up', pc(report.gaps.continue_up, 0)],
                  ['Continue down | gap down', pc(report.gaps.continue_down, 0)],
                ]} />
              )}
            </div>
            <div className="card">
              <h2>Streaks</h2>
              {report.streaks.note ? <p className="muted small">{report.streaks.note}</p> : (
                <KV rows={[
                  ['P(up) base', pc(report.streaks.p_up, 0)],
                  ['P(up | prev up)', pc(report.streaks.p_up_given_up, 0)],
                  ['P(up | 2 prev up)', pc(report.streaks.p_up_given_2up, 0)],
                  ['Longest up streak', `${report.streaks.longest_up} days`],
                  ['Longest down streak', `${report.streaks.longest_down} days`],
                ]} />
              )}
            </div>
          </div>

          {ch && !ch.note && (
            <>
              <h2 className="section-head">Quant character</h2>
              <div className="stats-grid">
                <div className="card">
                  <h2>Distribution shape</h2>
                  <KV rows={[
                    ['Skewness', num(ch.distribution?.skewness)],
                    ['Excess kurtosis', num(ch.distribution?.excess_kurtosis)],
                    ['Normal (JB 5%)', ch.distribution?.is_normal_5pct ? 'yes' : 'no'],
                    ['Hill tail index', num(ch.distribution?.hill_tail_index, 1)],
                    ['Student-t dof', num(ch.distribution?.student_t_dof, 1)],
                  ]} />
                </div>
                <div className="card">
                  <h2>Volatility</h2>
                  <KV rows={[
                    ['Yang–Zhang (ann.)', pc(ch.volatility?.annualised?.yang_zhang, 1)],
                    ['Close-to-close (ann.)', pc(ch.volatility?.annualised?.close_to_close, 1)],
                    ['Vol clustering', ch.volatility?.clustering_present ? 'yes (ARCH)' : 'no'],
                    ['GARCH persistence', num(ch.volatility?.garch_persistence, 3)],
                    ['Leverage effect', ch.volatility?.leverage_effect ? 'yes' : 'no'],
                  ]} />
                </div>
                <div className="card">
                  <h2>Mean reversion / trend</h2>
                  <KV rows={[
                    ['Verdict', String(ch.mean_reversion?.verdict ?? '—')],
                    ['Hurst (R/S)', num(ch.mean_reversion?.hurst_rs)],
                    ['DFA exponent', num(ch.mean_reversion?.dfa_exponent)],
                    ['Variance ratio q2', num(ch.mean_reversion?.variance_ratio_q2?.vr)],
                    ['ADF stationary', ch.mean_reversion?.adf_stationary_5pct ? 'yes' : 'no'],
                    ['OU half-life (bars)', num(ch.mean_reversion?.half_life_bars, 1)],
                  ]} />
                </div>
                <div className="card">
                  <h2>Predictability</h2>
                  <KV rows={[
                    ['P(up)', pc(ch.predictability?.conditional_direction?.['P(up)'], 0)],
                    ['P(up | up)', pc(ch.predictability?.conditional_direction?.['P(up_next | up_today)'], 0)],
                    ['P(up | down)', pc(ch.predictability?.conditional_direction?.['P(up_next | down_today)'], 0)],
                    ['Touch 1σ (empirical)', pc(ch.predictability?.touch_empirical?.['1sigma'], 0)],
                    ['Touch 2σ (empirical)', pc(ch.predictability?.touch_empirical?.['2sigma'], 0)],
                  ]} />
                </div>
              </div>
            </>
          )}
          {ch?.note && <p className="muted small">{ch.note}</p>}
        </>
      )}
      {report && report.performance.note && (
        <p className="muted">Not enough data in this range for the statistics.</p>
      )}
    </main>
  );
}
