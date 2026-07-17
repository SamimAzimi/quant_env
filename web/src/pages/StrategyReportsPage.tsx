import { useEffect, useState } from 'react';
import {
  api, type RunReport, type RunSummary, type RunTrades,
} from '../api';
import MultiLineChart from '../components/MultiLineChart';

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

function FrameTable({ name, frame }: {
  name: string;
  frame: { columns: string[]; data: unknown[][] };
}) {
  if (!frame?.columns || frame.data.length === 0) return null;
  return (
    <div className="card">
      <h2>{name.replace(/_/g, ' ')}</h2>
      <div style={{ overflowX: 'auto', maxHeight: 300, overflowY: 'auto' }}>
        <table className="data">
          <thead><tr>{frame.columns.map((c) => <th key={c}>{String(c)}</th>)}</tr></thead>
          <tbody>
            {frame.data.slice(0, 60).map((row, i) => (
              <tr key={i}>
                {row.map((v, j) => (
                  <td key={j}>
                    {typeof v === 'number' ? Number(v.toFixed(4)) : String(v ?? '—')}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const SHOW_FRAMES = ['exit_reasons', 'monthly_returns', 'by_session', 'by_dow'];

/** Browse backtest runs saved by the pipeline into the app database. */
export default function StrategyReportsPage() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [sel, setSel] = useState('');
  const [report, setReport] = useState<RunReport | null>(null);
  const [trades, setTrades] = useState<RunTrades | null>(null);
  const [page, setPage] = useState(0);
  const [error, setError] = useState('');
  const PAGE = 50;

  useEffect(() => {
    api.get<RunSummary[]>('/api/strategy-reports')
      .then((r) => { setRuns(r); if (r.length && !sel) setSel(r[0].run_id); })
      .catch((e) => setError(String(e)));
  }, []);

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
  const equitySeries = report && report.equity.length > 1 ? [{
    name: 'equity',
    points: report.equity
      .filter((p) => p.time)
      .map((p) => ({
        time: Math.floor(new Date(`${p.time}Z`).getTime() / 1000),
        value: p.equity,
      })),
  }] : [];

  return (
    <main className="page">
      <div className="page-toolbar">
        <h1 className="page-title">Strategy reports</h1>
        <label className="row small">
          <span className="muted">Run</span>
          <select value={sel} onChange={(e) => setSel(e.target.value)}>
            {runs.map((r) => (
              <option key={r.run_id} value={r.run_id}>
                {r.run_id} — {r.strategy || '?'} ({r.n_trades} trades)
              </option>
            ))}
          </select>
        </label>
      </div>

      {runs.length === 0 && !error && (
        <p className="muted">
          No stored runs yet. Backtests persist here automatically:
          <code> run_pipeline(PipelineConfig(...))</code> saves into the app
          database (store_backend="mysql", the default).
        </p>
      )}
      {error && <p className="error">{error}</p>}

      {report && (
        <>
          <p className="small muted">
            {report.asset} · {report.timeframe} · {report.strategy} ·
            saved {report.saved_at.slice(0, 16).replace('T', ' ')} UTC ·
            {report.n_trades} trades
          </p>
          <div className="tile-grid">
            <Tile label="Net profit" value={num(m.net_profit)} />
            <Tile label="Total return %" value={num(m.total_return_pct)} />
            <Tile label="Win rate" value={num(m.win_rate)} />
            <Tile label="Profit factor" value={num(m.profit_factor)} />
            <Tile label="Sharpe" value={num(m.sharpe)} />
            <Tile label="Sortino" value={num(m.sortino)} />
            <Tile label="Max DD %" value={num(m.max_drawdown_pct)} />
            <Tile label="Expectancy R" value={num(m.expectancy_r)} />
          </div>

          {equitySeries.length > 0 && (
            <div className="card" style={{ marginTop: 14 }}>
              <h2>Equity curve</h2>
              <MultiLineChart series={equitySeries} />
            </div>
          )}

          <div className="stats-grid" style={{ marginTop: 14 }}>
            {SHOW_FRAMES.filter((f) => report.frames[f]).map((f) => (
              <FrameTable key={f} name={f} frame={report.frames[f]} />
            ))}
            <div className="card">
              <h2>All metrics</h2>
              <div style={{ maxHeight: 300, overflowY: 'auto' }}>
                <table className="data">
                  <tbody>
                    {Object.entries(m).map(([k, v]) => (
                      <tr key={k}><th className="muted">{k}</th><td>{num(v, 4)}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
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
                      <tr key={t.trade_id} className={ (t.net_pnl ?? 0) >= 0 ? '' : 'row-open'}>
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
