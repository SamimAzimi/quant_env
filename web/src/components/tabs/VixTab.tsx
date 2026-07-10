import { useState } from 'react';
import { api } from '../../api';

export default function VixTab({ onSaved }: { onSaved: () => void }) {
  const [value, setValue] = useState('');
  const [status, setStatus] = useState('');

  const save = async () => {
    setStatus('');
    try {
      await api.post('/api/vix', { value: Number(value) });
      setValue('');
      setStatus('Saved ✓ — will show on tomorrow’s stats');
      onSaved();
    } catch (e) {
      setStatus(String(e));
    }
  };

  return (
    <div>
      <label className="field">
        <span>VIX level (timestamped now, UTC)</span>
        <input
          type="number" step="0.01" min="0"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="e.g. 17.42"
        />
      </label>
      <button className="primary" disabled={value === ''} onClick={save}>Save VIX</button>
      {status && <p className={status.startsWith('Saved') ? 'small' : 'error'}>{status}</p>}
    </div>
  );
}
