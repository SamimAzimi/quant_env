import { useEffect, useState } from 'react';
import { api, type Trade } from '../api';
import UtcDateTimeInput from '../components/tabs/UtcDateTimeInput';

const fmt = (iso: string | null) =>
  iso ? `${iso.slice(0, 16).replace('T', ' ')} UTC` : '—';

/** Today's recorded + open trades, editable (exit time/reason come later). */
export default function TradesSection({ refreshKey }: { refreshKey: number }) {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [editing, setEditing] = useState<Trade | null>(null);
  const [error, setError] = useState('');

  const load = () =>
    api.get<Trade[]>('/api/trades').then(setTrades).catch((e) => setError(String(e)));

  useEffect(() => { load(); }, [refreshKey]);

  const save = async () => {
    if (!editing) return;
    await api.patch(`/api/trades/${editing.id}`, {
      exit_time: editing.exit_time,
      exit_reason: editing.exit_reason,
      entry_reason: editing.entry_reason,
      tp: editing.tp,
      sl: editing.sl,
      remarks: editing.remarks,
    });
    setEditing(null);
    load();
  };

  return (
    <div className="card">
      <h2>Trades — today &amp; open</h2>
      {error && <p className="error">{error}</p>}
      {trades.length === 0 && <p className="muted small">No trades today.</p>}
      {trades.map((t) => (
        <div key={t.id} className="news-item">
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <span>
              <strong>#{t.id}</strong>{' '}
              <span className="small muted">{fmt(t.entry_time)} → {fmt(t.exit_time)}</span>{' '}
              {!t.exit_time && <span className="chip effect">OPEN</span>}
            </span>
            <button className="ghost small" onClick={() => setEditing({ ...t })}>Edit</button>
          </div>
          <div className="small muted">
            {t.entry_reason && <>In: {t.entry_reason} · </>}
            {t.exit_reason && <>Out: {t.exit_reason} · </>}
            TP {t.tp ?? '—'} / SL {t.sl ?? '—'}
            {t.remarks && <> · {t.remarks}</>}
          </div>
        </div>
      ))}

      {editing && (
        <div className="overlay-backdrop" onClick={() => setEditing(null)}>
          <div className="overlay" onClick={(e) => e.stopPropagation()}>
            <div className="overlay-head">
              <h2>Edit trade #{editing.id}</h2>
              <button className="overlay-close" onClick={() => setEditing(null)}>×</button>
            </div>
            <div className="overlay-body">
              <UtcDateTimeInput
                label="Exit Time (UTC)"
                value={editing.exit_time ?? ''}
                onChange={(v) => setEditing({ ...editing, exit_time: v || null })}
              />
              <label className="field">
                <span>Exit Reason</span>
                <textarea rows={2} value={editing.exit_reason ?? ''}
                  onChange={(e) => setEditing({ ...editing, exit_reason: e.target.value })} />
              </label>
              <label className="field">
                <span>Entry Reason</span>
                <textarea rows={2} value={editing.entry_reason}
                  onChange={(e) => setEditing({ ...editing, entry_reason: e.target.value })} />
              </label>
              <div className="row">
                <label className="field" style={{ flex: 1 }}>
                  <span>TP</span>
                  <input type="number" step="any" value={editing.tp ?? ''}
                    onChange={(e) => setEditing({ ...editing, tp: e.target.value === '' ? null : Number(e.target.value) })} />
                </label>
                <label className="field" style={{ flex: 1 }}>
                  <span>SL</span>
                  <input type="number" step="any" value={editing.sl ?? ''}
                    onChange={(e) => setEditing({ ...editing, sl: e.target.value === '' ? null : Number(e.target.value) })} />
                </label>
              </div>
              <label className="field">
                <span>Remarks</span>
                <textarea rows={2} value={editing.remarks}
                  onChange={(e) => setEditing({ ...editing, remarks: e.target.value })} />
              </label>
              <button className="primary" onClick={save}>Save changes</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
