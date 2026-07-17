import { useEffect, useState } from 'react';
import {
  api, type MetricGroup, type MonteCarlo, type RunReport, type RunSummary,
  type RunTrades,
} from '../api';
import MultiLineChart from '../components/MultiLineChart';

const POS = '#26a69a';
const NEG = '#ef5350';
const ACCENT = '#5ec8f0';

/** Dashboard-style value formatting (money / pct / pct_frac / int / …). */
function fmt(v: number | string | null | undefined, kind = 'num'): string {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'string') return v;
  if (!Number.isFinite(v)) return '—';
  switch (kind) {
    case 'money': return v.toLocaleString('en-US', { maximumFractionDigits: 0 });
    case 'pct': return `${v.toFixed(2)}%`;
    case 'pct_frac': return `${(v * 100).toFixed(1)}%`;
    case 'int': return Math.round(v).toLocaleString('en-US');
    case 'bool': return v ? 'Yes' : 'No';
    default: return v.toFixed(3);
  }
}

const num = (x: number | string | null | undefined, d = 2) =>
  x === null || x === undefined ? '—'
    : typeof x === 'number' ? x.toFixed(d) : String(x);

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="stat-tile">
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

// headline KPI strip — mirrors the old dashboard's METRIC_FMT cards
const HEADLINE: [string, string, string][] = [
  ['net_profit', 'Net profit', 'money'],
  ['total_return_pct', 'Total return', 'pct'],
  ['final_equity', 'Final equity', 'money'],
  ['win_rate', 'Win rate', 'pct_frac'],
  ['profit_factor', 'Profit factor', 'num'],
  ['sharpe', 'Sharpe', 'num'],
  ['sortino', 'Sortino', 'num'],
  ['max_drawdown_pct', 'Max drawdown', 'pct'],
  ['expectancy_r', 'Expectancy (R)', 'num'],
  ['total_trades', 'Trades', 'int'],
];

interface Frame { columns: string[]; data: unknown[][] }

/** pandas-split frame → [label, value] rows (first col label, last numeric). */
function frameRows(frame?: Frame): { label: string; value: number }[] {
  if (!frame?.data?.length) return [];
  const out: { label: string; value: number }[] = [];
  for (const row of frame.data) {
    let value = NaN;
    for (let i = row.length - 1; i >= 1; i--) {
      const v = Number(row[i]);
      if (Number.isFinite(v)) { value = v; break; }
    }
    if (!Number.isFinite(value)) continue;
    let label = String(row[0] ?? '');
    if (/^\d{4}-\d{2}-\d{2}T/.test(label)) label = label.slice(0, 10);
    out.push({ label, value });
  }
  return out;
}

/** Vertical SVG bar chart for small categorical series. */
function MiniBars({ rows, format, every = 1 }: {
  rows: { label: string; value: number }[];
  format?: (v: number) => string;
  every?: number;                       // label every Nth bar
}) {
  if (!rows.length) return <p className="muted small">no data</p>;
  const W = 560; const H = 190; const PAD = 6; const LABEL_H = 16;
  const max = Math.max(...rows.map((r) => Math.abs(r.value)), 1e-12);
  const bw = (W - 2 * PAD) / rows.length;
  const hasNeg = rows.some((r) => r.value < 0);
  const zero = hasNeg ? (H - LABEL_H) / 2 : H - LABEL_H;
  const scale = (hasNeg ? zero - 8 : H - LABEL_H - 12) / max;
  const f = format ?? ((v: number) => v.toFixed(2));
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto' }}>
      <line x1={PAD} x2={W - PAD} y1={zero} y2={zero} stroke="#2a3140" />
      {rows.map((r, i) => {
        const h = Math.abs(r.value) * scale;
        const y = r.value >= 0 ? zero - h : zero;
        return (
          <g key={i}>
            <rect x={PAD + i * bw + 1} y={y} width={Math.max(bw - 2, 1)} height={Math.max(h, 0.5)}
              fill={r.value >= 0 ? POS : NEG} opacity={0.85}>
              <title>{r.label}: {f(r.value)}</title>
            </rect>
            {i % every === 0 && rows.length <= 40 && (
              <text x={PAD + i * bw + bw / 2} y={H - 3} textAnchor="middle"
                fontSize={9} fill="#8b93a3">{r.label.length > 9 ? r.label.slice(0, 9) : r.label}</text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

/** Plain SVG line for rolling series (x = position). */
function MiniLine({ rows, format }: {
  rows: { label: string; value: number }[];
  format?: (v: number) => string;
}) {
  if (rows.length < 2) return <p className="muted small">no data</p>;
  const W = 560; const H = 170; const PAD = 8;
  const vals = rows.map((r) => r.value);
  const lo = Math.min(...vals); const hi = Math.max(...vals);
  const span = hi - lo || 1;
  const x = (i: number) => PAD + (i / (rows.length - 1)) * (W - 2 * PAD);
  const y = (v: number) => PAD + (1 - (v - lo) / span) * (H - 2 * PAD);
  const pts = rows.map((r, i) => `${x(i).toFixed(1)},${y(r.value).toFixed(1)}`).join(' ');
  const f = format ?? ((v: number) => v.toFixed(2));
  const zeroY = lo < 0 && hi > 0 ? y(0) : null;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto' }}>
      {zeroY !== null && <line x1={PAD} x2={W - PAD} y1={zeroY} y2={zeroY} stroke="#2a3140" />}
      <polyline points={pts} fill="none" stroke={ACCENT} strokeWidth={1.6} />
      <text x={W - PAD} y={12} textAnchor="end" fontSize={10} fill="#8b93a3">
        last {f(rows[rows.length - 1].value)} · min {f(lo)} · max {f(hi)}
      </text>
    </svg>
  );
}

function ChartCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="card">
      <h2>{title}</h2>
      {children}
    </div>
  );
}

function MetricGroups({ groups }: { groups: MetricGroup[] }) {
  return (
    <div className="card" style={{ marginTop: 14 }}>
      <h2>Detailed metrics</h2>
      {groups.map((g) => (
        <details key={g.name} open={g.name === 'Performance' || g.name === 'Risk & return'}>
          <summary style={{ cursor: 'pointer', padding: '6px 0', fontWeight: 600 }}>
            {g.name} <span className="muted small">({g.items.length})</span>
          </summary>
          <div className="tile-grid" style={{ marginBottom: 8 }}>
            {g.items.map((it) => (
              <Tile key={it.key} label={it.label} value={fmt(it.value, it.kind)} />
            ))}
          </div>
        </details>
      ))}
    </div>
  );
}

function MonteCarloCard({ mc }: { mc: MonteCarlo }) {
  const bars = mc.hist.counts.map((c, i) => ({
    label: `${mc.hist.edges[i]}%`, value: c,
  }));
  return (
    <div className="card" style={{ marginTop: 14 }}>
      <h2>Monte Carlo — bootstrap of trade returns</h2>
      <div className="tile-grid">
        <Tile label="Median return" value={`${mc.median_return.toFixed(2)}%`} />
        <Tile label="P10 / P90 return"
          value={`${mc.p10_return.toFixed(1)}% / ${mc.p90_return.toFixed(1)}%`} />
        <Tile label="Prob. of profit" value={`${mc.prob_profit.toFixed(1)}%`} />
        <Tile label="Median max DD" value={`${mc.median_maxdd.toFixed(2)}%`} />
        <Tile label="P90 / worst max DD"
          value={`${mc.p90_maxdd.toFixed(1)}% / ${mc.worst_maxdd.toFixed(1)}%`} />
      </div>
      <MiniBars rows={bars} every={5} format={(v) => `${v} paths`} />
      <p className="muted small">
        {mc.n_paths.toLocaleString()} bootstrapped equity paths over {mc.n_trades} trades;
        histogram of terminal returns.
      </p>
    </div>
  );
}

/** Browse backtest runs saved by the pipeline into the app database. */
export default function StrategyReportsPage() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [sel, setSel] = useState('');
  const [report, setReport] = useState<RunReport | null>(null);
  const [trades, setTrades] = useState<RunTrades | null>(null);
  const [page, setPage] = useState(0);
  const [error, setError] = useState('');
  const PAGE = 50;

  const loadRuns = () => {
    api.get<RunSummary[]>('/api/strategy-reports')
      .then((r) => {
        setRuns(r);
        if (r.length === 0) { setSel(''); setReport(null); setTrades(null); }
        else if (!sel || !r.some((x) => x.run_id === sel)) setSel(r[0].run_id);
      })
      .catch((e) => setError(String(e)));
  };
  useEffect(loadRuns, []);

  const deleteRun = async (id: string) => {
    if (!window.confirm(`Delete stored run "${id}"? Its metrics, trades, equity and frames are all removed.`)) return;
    try {
      await api.delete(`/api/strategy-reports/${encodeURIComponent(id)}`);
      loadRuns();
    } catch (e) { setError(String(e)); }
  };

  const deleteAll = async () => {
    if (!window.confirm(`Delete ALL ${runs.length} stored runs? Every metric, trade, equity point and frame is removed from the database.`)) return;
    try {
      await api.delete('/api/strategy-reports');
      loadRuns();
    } catch (e) { setError(String(e)); }
  };

  useEffect(() => {
    if (!sel) return;
    setReport(null); setTrades(null); setPage(0); setError('');
    api.get<RunReport>(`/api/strategy-reports/${encodeURIComponent(sel)}`)
      .then(setReport).catch((e) => setError(String(e)));
  }, [sel]);

  useEffect(() => {
    if (!sel) return;
    api.get<RunTrades>(
      `/api/strategy-reports/${encodeURIComponent(sel)}/trades?limit=${PAGE}&offset=${page * PAGE}`)
      .then(setTrades).catch(() => {});
  }, [sel, page]);

  const m = report?.metrics ?? {};
  const frames = report?.frames ?? {};

  // lightweight-charts needs strictly ascending, UNIQUE times. Multi-lot
  // exits close on the same bar, so many equity points share a timestamp —
  // keep the LAST equity value per timestamp (the bar's final state).
  const timed = new Map<number, number>();
  for (const p of report?.equity ?? []) {
    if (!p.time) continue;
    const t = Math.floor(new Date(`${p.time}Z`).getTime() / 1000);
    if (Number.isFinite(t)) timed.set(t, p.equity);
  }
  const equitySeries = [...timed.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([time, value]) => ({ time, value }));
  // drawdown % from the stored equity (running-max, like the old dashboard)
  let peak = -Infinity;
  const ddSeries = equitySeries.map((p) => {
    peak = Math.max(peak, p.value);
    return { time: p.time, value: peak > 0 ? ((p.value / peak) - 1) * 100 : 0 };
  });
  // fallback when timestamps are missing: plot per trade step instead
  const equityRows = (report?.equity ?? []).map((p, i) => ({
    label: String(p.step ?? i), value: p.equity,
  }));
  let peak2 = -Infinity;
  const ddRows = equityRows.map((p) => {
    peak2 = Math.max(peak2, p.value);
    return { label: p.label, value: peak2 > 0 ? ((p.value / peak2) - 1) * 100 : 0 };
  });

  const exitRows = frameRows(frames.exit_reasons);
  const monthlyRows = frameRows(frames.monthly_returns)
    .map((r) => ({ label: r.label.slice(0, 7), value: r.value * 100 }));
  const cs = report?.cost_summary ?? {};

  return (
    <main className="page">
      <div className="page-toolbar">
        <h1 className="page-title">Strategy reports</h1>
        <label className="row small">
          <span className="muted">Run</span>
          <select value={sel} onChange={(e) => setSel(e.target.value)}>
            {runs.map((r) => (
              <option key={r.run_id} value={r.run_id}>
                {r.rank ? `#${r.rank} ` : ''}{r.run_id} — {r.strategy || '?'} ({r.n_trades} trades)
              </option>
            ))}
          </select>
        </label>
      </div>

      {runs.length === 0 && !error && (
        <p className="muted">
          No stored runs yet. Backtests persist here automatically:
          <code> run_pipeline(PipelineConfig(...))</code> saves into the app
          database. The pipeline prints the exact database it saved to — it
          must match the <code>MARKET_PREP_DB_URL</code> this server uses.
        </p>
      )}
      {error && <p className="error">{error}</p>}

      {runs.length > 0 && (
        <div className="card" style={{ marginBottom: 14 }}>
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <h2>Stored runs ({runs.length})</h2>
            <button className="ghost small" onClick={deleteAll}>🗑 Delete all</button>
          </div>
          <p className="muted small">
            Every strategy run saved in the database. Click a row to open its
            report; Delete removes the run and all of its metrics, trades,
            equity points and frames.
          </p>
          <div style={{ overflowX: 'auto', maxHeight: 280, overflowY: 'auto' }}>
            <table className="data">
              <thead><tr>
                <th>rank</th><th>run</th><th>strategy</th><th>asset</th>
                <th>tf</th><th>trades</th><th>net profit</th><th>score</th>
                <th>saved (UTC)</th><th />
              </tr></thead>
              <tbody>
                {runs.map((r) => (
                  <tr key={r.run_id} onClick={() => setSel(r.run_id)}
                    style={{ cursor: 'pointer' }}
                    className={r.run_id === sel ? 'row-open' : ''}>
                    <td>{r.rank ? `#${r.rank}` : '—'}</td>
                    <td>{r.run_id}</td>
                    <td>{r.strategy || '—'}</td>
                    <td>{r.asset}</td>
                    <td>{r.timeframe || '—'}</td>
                    <td>{r.n_trades}</td>
                    <td>{num(r.headline?.net_profit as number | null)}</td>
                    <td>{num(r.composite_score)}</td>
                    <td className="small">{r.saved_at.slice(0, 16).replace('T', ' ')}</td>
                    <td>
                      <button className="ghost small"
                        onClick={(e) => { e.stopPropagation(); deleteRun(r.run_id); }}>
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {report && (
        <>
          <p className="small muted">
            {report.asset} · {report.timeframe} · {report.strategy} ·
            saved {report.saved_at.slice(0, 16).replace('T', ' ')} UTC ·
            {report.n_trades} trades
          </p>

          <div className="tile-grid">
            <Tile label="Composite score" value={num(report.composite_score)} />
            <Tile label="Rank"
              value={report.rank ? `#${report.rank} / ${report.n_runs}` : '—'} />
            {HEADLINE.filter(([k]) => m[k] !== undefined).map(([k, label, kind]) => (
              <Tile key={k} label={label} value={fmt(m[k], kind)} />
            ))}
          </div>

          {(equitySeries.length > 1 || equityRows.length > 1) && (
            <div className="stats-grid" style={{ marginTop: 14 }}>
              <div className="card">
                <h2>Equity curve</h2>
                {equitySeries.length > 1
                  ? <MultiLineChart series={[{ name: 'equity', points: equitySeries }]} />
                  : <MiniLine rows={equityRows} />}
              </div>
              <div className="card">
                <h2>Drawdown (%)</h2>
                {ddSeries.length > 1
                  ? <MultiLineChart series={[{ name: 'drawdown', points: ddSeries }]} suffix="%" />
                  : <MiniLine rows={ddRows} format={(v) => `${v.toFixed(2)}%`} />}
              </div>
            </div>
          )}

          <div className="stats-grid" style={{ marginTop: 14 }}>
            {exitRows.length > 0 && (
              <ChartCard title="Exit reasons">
                <MiniBars rows={exitRows} format={(v) => `${v} trades`} />
              </ChartCard>
            )}
            {monthlyRows.length > 0 && (
              <ChartCard title="Monthly returns (%)">
                <MiniBars rows={monthlyRows} format={(v) => `${v.toFixed(2)}%`} />
              </ChartCard>
            )}
            {frameRows(frames.rolling_sharpe).length > 1 && (
              <ChartCard title="Rolling Sharpe">
                <MiniLine rows={frameRows(frames.rolling_sharpe)} />
              </ChartCard>
            )}
            {frameRows(frames.rolling_win_rate).length > 1 && (
              <ChartCard title="Rolling win rate">
                <MiniLine rows={frameRows(frames.rolling_win_rate)}
                  format={(v) => `${(v * 100).toFixed(1)}%`} />
              </ChartCard>
            )}
            {frameRows(frames.by_session).length > 0 && (
              <ChartCard title="Profit by session">
                <MiniBars rows={frameRows(frames.by_session)}
                  format={(v) => v.toFixed(2)} />
              </ChartCard>
            )}
            {frameRows(frames.by_dow).length > 0 && (
              <ChartCard title="Profit by day of week">
                <MiniBars rows={frameRows(frames.by_dow)}
                  format={(v) => v.toFixed(2)} />
              </ChartCard>
            )}
            {frameRows(frames.by_hour).length > 0 && (
              <ChartCard title="Profit by hour">
                <MiniBars rows={frameRows(frames.by_hour)} every={3}
                  format={(v) => v.toFixed(2)} />
              </ChartCard>
            )}
            {frameRows(frames.by_month).length > 0 && (
              <ChartCard title="Profit by month">
                <MiniBars rows={frameRows(frames.by_month)}
                  format={(v) => v.toFixed(2)} />
              </ChartCard>
            )}
          </div>

          <div className="stats-grid" style={{ marginTop: 14 }}>
            {report.long_short.length > 0 && (
              <div className="card">
                <h2>Long vs short</h2>
                <table className="data">
                  <thead><tr>
                    <th>side</th><th>trades</th><th>wins</th><th>win rate</th>
                    <th>net P&amp;L</th><th>avg P&amp;L</th>
                  </tr></thead>
                  <tbody>
                    {report.long_short.map((r) => (
                      <tr key={r.side}>
                        <td>{r.side}</td><td>{r.trades}</td><td>{r.wins}</td>
                        <td>{r.win_rate_pct}%</td>
                        <td style={{ color: r.net_pnl >= 0 ? POS : NEG }}>
                          {r.net_pnl.toFixed(2)}
                        </td>
                        <td>{r.avg_pnl.toFixed(2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <div className="card">
              <h2>Costs</h2>
              <div className="tile-grid">
                <Tile label="Trades" value={String(cs.trades ?? '—')} />
                <Tile label="Spread" value={num(cs.spread_cost)} />
                <Tile label="Commission" value={num(cs.commission_cost)} />
                <Tile label="Financing" value={num(cs.financing_cost)} />
                <Tile label="Total cost" value={num(cs.total_cost)} />
                <Tile label="Gross P&L" value={num(cs.gross_pnl)} />
                <Tile label="Net P&L" value={num(cs.net_pnl)} />
              </div>
            </div>
          </div>

          {report.monte_carlo && <MonteCarloCard mc={report.monte_carlo} />}

          <MetricGroups groups={report.metric_groups} />

          <div className="card" style={{ marginTop: 14 }}>
            <h2>Strategy / run metadata</h2>
            <div style={{ maxHeight: 300, overflowY: 'auto' }}>
              <table className="data">
                <tbody>
                  {Object.entries(report.metadata).map(([k, v]) => (
                    <tr key={k}>
                      <th className="muted">{k}</th>
                      <td>{typeof v === 'object' ? JSON.stringify(v) : String(v)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {trades && (
            <div className="card" style={{ marginTop: 14 }}>
              <div className="row" style={{ justifyContent: 'space-between' }}>
                <h2>Trades ({trades.total})</h2>
                <span className="row small">
                  <button className="ghost small" disabled={page === 0}
                    onClick={() => setPage((p) => p - 1)}>‹ prev</button>
                  <span className="muted">
                    {page * PAGE + 1}–{Math.min((page + 1) * PAGE, trades.total)}
                  </span>
                  <button className="ghost small"
                    disabled={(page + 1) * PAGE >= trades.total}
                    onClick={() => setPage((p) => p + 1)}>next ›</button>
                </span>
              </div>
              <div style={{ overflowX: 'auto' }}>
                <table className="data">
                  <thead><tr>
                    <th>id</th><th>side</th><th>entry</th><th>exit</th>
                    <th>entry px</th><th>exit px</th><th>reason</th>
                    <th>net pnl</th><th>R</th><th>setup</th><th>lot</th>
                  </tr></thead>
                  <tbody>
                    {trades.rows.map((t) => (
                      <tr key={t.trade_id} className={(t.net_pnl ?? 0) >= 0 ? '' : 'row-open'}>
                        <td>{t.trade_id}</td><td>{t.side ?? '—'}</td>
                        <td className="small">{t.entry_time?.slice(5, 16).replace('T', ' ') ?? '—'}</td>
                        <td className="small">{t.exit_time?.slice(5, 16).replace('T', ' ') ?? '—'}</td>
                        <td>{num(t.entry_price, 5)}</td><td>{num(t.exit_price, 5)}</td>
                        <td>{t.exit_reason ?? '—'}</td>
                        <td>{num(t.net_pnl)}</td><td>{num(t.r_multiple)}</td>
                        <td>{String(t.extra?.setup ?? '—')}</td>
                        <td>{String(t.extra?.lot ?? '—')}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </main>
  );
}
