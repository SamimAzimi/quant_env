import { useEffect, useState } from 'react';
import { api, withParams, type ReturnsSeries, type SessionSpan } from '../api';
import ReturnsChart, { SERIES_COLORS } from '../components/ReturnsChart';
import { SESSION_LEGEND } from '../components/sessionBands';

interface Props {
  timeframes: string[];
  available: string[];
  defaults: string[];
  date: string;   // '' = today
}

/** Color-coded cumulative log returns across yesterday, multi-asset. */
export default function PreDayStats({ timeframes, available, defaults, date }: Props) {
  const [tf, setTf] = useState('15m');
  const [selected, setSelected] = useState<string[]>(defaults);
  const [series, setSeries] = useState<ReturnsSeries[]>([]);
  const [sessions, setSessions] = useState<SessionSpan[]>([]);
  const [error, setError] = useState('');

  useEffect(() => { setSelected(defaults); }, [defaults]);

  useEffect(() => {
    if (selected.length === 0) { setSeries([]); return; }
    setError('');
    api.get<{ series: ReturnsSeries[]; sessions: SessionSpan[] }>(
      withParams('/api/stats/returns', { tf, assets: selected.join(','), date }))
      .then((r) => { setSeries(r.series); setSessions(r.sessions ?? []); })
      .catch((e) => setError(String(e)));
  }, [tf, selected, date]);

  const toggle = (asset: string) =>
    setSelected((s) => (s.includes(asset) ? s.filter((a) => a !== asset) : [...s, asset]));

  const choices = available.length > 0 ? available : defaults;

  return (
    <div className="card span-2">
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <h2>Pre-day stats — log returns</h2>
        <select value={tf} onChange={(e) => setTf(e.target.value)}>
          {timeframes.map((t) => <option key={t}>{t}</option>)}
        </select>
      </div>
      <div className="row" style={{ marginBottom: 8 }}>
        {choices.map((asset) => (
          <label key={asset} className="chip" style={{ cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={selected.includes(asset)}
              onChange={() => toggle(asset)}
              style={{ marginRight: 4 }}
            />
            {asset}
          </label>
        ))}
      </div>
      {error && <p className="error">{error}</p>}
      {series.length > 0 ? (
        <>
          <ReturnsChart series={series} sessions={sessions} />
          <div className="row small" style={{ marginTop: 6 }}>
            {series.map((s, i) => (
              <span key={s.asset}>
                <span className="legend-dot"
                  style={{ background: SERIES_COLORS[i % SERIES_COLORS.length] }} />
                {s.asset}
              </span>
            ))}
            <span className="muted">·</span>
            {[...new Map(sessions.map((s) => [s.key, s])).values()].map((s) => (
              <span key={s.key} className="muted">
                <span className="legend-dot"
                  style={{ background: SESSION_LEGEND[s.key] ?? '#8b93a3', opacity: 0.6 }} />
                {s.name}
              </span>
            ))}
          </div>
        </>
      ) : (
        <p className="muted small">No return data — select assets or download data first.</p>
      )}
    </div>
  );
}
