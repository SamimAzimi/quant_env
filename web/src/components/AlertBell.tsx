import { useEffect, useRef, useState } from 'react';
import { api, localInputToUtc, utcToLocalInput, type AlertItem } from '../api';

/** Header bell: shows pending alert count; the panel lists incoming alerts
 *  with inline edit (local time + message) and delete. */
export default function AlertBell({ refreshKey }: { refreshKey: number }) {
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<AlertItem | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  const load = () => api.get<AlertItem[]>('/api/alerts').then(setAlerts).catch(() => {});

  useEffect(() => {
    load();
    const timer = window.setInterval(load, 30_000);   // sent alerts vanish
    return () => window.clearInterval(timer);
  }, [refreshKey]);

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, []);

  const saveEdit = async () => {
    if (!editing) return;
    await api.patch(`/api/alerts/${editing.id}`, {
      due_time: editing.due_time.endsWith('Z') ? editing.due_time : `${editing.due_time}Z`,
      message: editing.message,
    });
    setEditing(null);
    load();
  };

  const remove = async (id: number) => {
    await api.delete(`/api/alerts/${id}`);
    load();
  };

  return (
    <div className="bell-wrap" ref={ref}>
      <button className="bell" aria-label="Alerts" onClick={() => setOpen((v) => !v)}>
        🔔
        {alerts.length > 0 && <span className="bell-badge">{alerts.length}</span>}
      </button>
      {open && (
        <div className="bell-panel">
          <div className="small muted" style={{ padding: '4px 8px' }}>
            Incoming alerts (times shown in your local zone)
          </div>
          {alerts.length === 0 && (
            <p className="muted small" style={{ padding: '0 8px 8px' }}>
              No pending alerts. Add one via Record → Alert.
            </p>
          )}
          {alerts.map((a) => (
            <div key={a.id} className="bell-item">
              {editing?.id === a.id ? (
                <>
                  <input
                    type="datetime-local"
                    value={utcToLocalInput(editing.due_time)}
                    onChange={(e) => setEditing({
                      ...editing, due_time: localInputToUtc(e.target.value),
                    })}
                  />
                  <textarea
                    rows={2}
                    value={editing.message}
                    onChange={(e) => setEditing({ ...editing, message: e.target.value })}
                  />
                  <div className="row">
                    <button className="primary" onClick={saveEdit}>Save</button>
                    <button className="ghost" onClick={() => setEditing(null)}>Cancel</button>
                  </div>
                </>
              ) : (
                <>
                  <div className="row" style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }}>
                    <strong className="small">
                      {new Date(`${a.due_time}Z`).toLocaleString(undefined, {
                        weekday: 'short', day: '2-digit', month: 'short',
                        hour: '2-digit', minute: '2-digit',
                      })}
                    </strong>
                    <span className="row" style={{ flexWrap: 'nowrap' }}>
                      <button className="ghost small" onClick={() => setEditing({ ...a })}>
                        Edit
                      </button>
                      <button className="ghost small danger" onClick={() => remove(a.id)}>
                        Delete
                      </button>
                    </span>
                  </div>
                  <div className="small">{a.message}</div>
                </>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
