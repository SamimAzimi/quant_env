import { useEffect, useState } from 'react';
import { api, type EconReport } from '../api';

/** Incoming economic reports with inline edit of actual + beat/miss. */
export default function MacroSection({ refreshKey }: { refreshKey: number }) {
  const [reports, setReports] = useState<EconReport[]>([]);
  const [error, setError] = useState('');

  const load = () =>
    api.get<EconReport[]>('/api/econ-reports')
      .then(setReports)
      .catch((e) => setError(String(e)));

  useEffect(() => { load(); }, [refreshKey]);

  const update = async (id: number, patch: Partial<EconReport>) => {
    await api.patch(`/api/econ-reports/${id}`, patch);
    load();
  };

  return (
    <div className="card">
      <h2>Macro — economic reports</h2>
      {error && <p className="error">{error}</p>}
      {reports.length === 0 ? (
        <p className="muted small">No reports recorded. Use Record → Economic Reports.</p>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table className="data">
            <thead>
              <tr>
                <th>Report</th><th>Forecast</th><th>Previous</th><th>Actual</th><th>Result</th>
              </tr>
            </thead>
            <tbody>
              {reports.map((r) => (
                <tr key={r.id}>
                  <td>{r.name}</td>
                  <td>{r.forecast || '—'}</td>
                  <td>{r.previous || '—'}</td>
                  <td>
                    <input
                      style={{ width: 70 }}
                      defaultValue={r.actual ?? ''}
                      onBlur={(e) => {
                        const v = e.target.value.trim();
                        if (v !== (r.actual ?? '')) update(r.id, { actual: v });
                      }}
                    />
                  </td>
                  <td>
                    <select
                      value={r.outcome ?? ''}
                      className={r.outcome ? `outcome-${r.outcome}` : ''}
                      onChange={(e) =>
                        update(r.id, { outcome: (e.target.value || null) as EconReport['outcome'] })}
                    >
                      <option value="">—</option>
                      <option value="beat">Beat</option>
                      <option value="miss">Miss</option>
                      <option value="inline">Inline</option>
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
