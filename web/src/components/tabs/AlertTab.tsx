import { useState } from 'react';
import { api, localInputToUtc } from '../../api';

/** Schedule a one-shot Telegram alert. Time is entered in LOCAL time and
 *  stored as UTC; once delivered to the Telegram chat it deletes itself. */
export default function AlertTab({ onSaved }: { onSaved: () => void }) {
  const [when, setWhen] = useState('');
  const [message, setMessage] = useState('');
  const [status, setStatus] = useState('');

  const save = async () => {
    setStatus('');
    try {
      await api.post('/api/alerts', {
        due_time: localInputToUtc(when),
        message,
      });
      setWhen(''); setMessage('');
      setStatus('Saved ✓ — will be sent to Telegram and then removed');
      onSaved();
    } catch (e) {
      setStatus(String(e));
    }
  };

  return (
    <div>
      <label className="field">
        <span>
          When — your local time
          ({Intl.DateTimeFormat().resolvedOptions().timeZone})
        </span>
        <input
          type="datetime-local"
          value={when}
          onChange={(e) => setWhen(e.target.value)}
        />
      </label>
      <label className="field">
        <span>Alert message</span>
        <textarea
          rows={4}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder="e.g. CPI release in 15 minutes — flatten risk"
        />
      </label>
      <button className="primary" disabled={!when || !message.trim()} onClick={save}>
        Schedule alert
      </button>
      {status && <p className={status.startsWith('Saved') ? 'small' : 'error'}>{status}</p>}
    </div>
  );
}
