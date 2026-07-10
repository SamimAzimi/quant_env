import { useEffect, useState } from 'react';
import { api, type ReturnsSeries } from '../api';
import ReturnsChart, { SERIES_COLORS } from '../components/ReturnsChart';

interface Props {
  timeframes: string[];
  available: string[];
  defaults: string[];
}

/** Color-coded cumulative log returns across yesterday, multi-asset. */
export default function PreDayStats({ timeframes, available, defaults }: Props) {
  const [tf, setTf] = useState('15m');
  const [selected, setSelected] = useState<string[]>(defaults);
  const [series, setSeries] = useState<ReturnsSeries[]>([]);
  const [error, setError] = useState('');

  useEffect(() => { setSelected(defaults); }, [defaults]);

  useEffect(() => {
    if (selected.length === 0) { setSeries([]); return; }
    setError('');
    api.get<{ series: ReturnsSeries[] }>(
      `/api/stats/returns?tf=${tf}&assets=${selected.join(',')}`)
      .then((r) => setSeries(r.series))
      .catch((e) => setError(String(e)));
  }, [tf, selected]);

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
          <ReturnsChart series={series} />
          <div className="row small" style={{ marginTop: 6 }}>
            {series.map((s, i) => (
              <span key={s.asset}>
                <span className="legend-dot"
                  style={{ background: SERIES_COLORS[i % SERIES_COLORS.length] }} />
                {s.asset}
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
