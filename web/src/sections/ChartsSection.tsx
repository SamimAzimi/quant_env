import { useEffect, useState } from 'react';
import { api, withParams, type AssetChart } from '../api';
import CandleChart from '../components/CandleChart';
import { SESSION_LEGEND } from '../components/sessionBands';

interface ChartsResponse {
  charts: AssetChart[];
  errors: Record<string, string>;
}

interface Props {
  timeframes: string[];
  date: string;   // '' = today
}

/** Yesterday's movement per asset with pre-day and session key levels. */
export default function ChartsSection({ timeframes, date }: Props) {
  const [tf, setTf] = useState('15m');
  const [data, setData] = useState<ChartsResponse | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    setError('');
    api.get<ChartsResponse>(withParams('/api/stats/charts', { tf, date }))
      .then(setData)
      .catch((e) => setError(String(e)));
  }, [tf, date]);

  return (
    <div className="card span-2">
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <h2>Charts — yesterday</h2>
        <select value={tf} onChange={(e) => setTf(e.target.value)}>
          {timeframes.map((t) => <option key={t}>{t}</option>)}
        </select>
      </div>
      {error && <p className="error">{error}</p>}
      {data && data.charts.length > 0 && (
        <div className="row small" style={{ marginBottom: 6 }}>
          {[...new Map(data.charts[0].sessions.map((s) => [s.key, s])).values()].map((s) => (
            <span key={s.key} className="muted">
              <span className="legend-dot"
                style={{ background: SESSION_LEGEND[s.key] ?? '#8b93a3', opacity: 0.6 }} />
              {s.name}
            </span>
          ))}
        </div>
      )}
      <div className="charts-grid">
        {data?.charts.map((c) => (
          <div key={c.asset} className="chart-box">
            <h3>{c.asset} <span className="muted small">{c.day} · {c.timeframe}</span></h3>
            <CandleChart data={c} />
          </div>
        ))}
      </div>
      {data && Object.keys(data.errors).length > 0 && (
        <p className="small muted">
          No data: {Object.keys(data.errors).join(', ')} — run libs/data_manager.py to download.
        </p>
      )}
    </div>
  );
}
