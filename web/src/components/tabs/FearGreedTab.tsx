import { useState } from 'react';
import { api } from '../../api';
import Gauge from '../Gauge';

export default function FearGreedTab({ onSaved }: { onSaved: () => void }) {
  const [value, setValue] = useState(50);
  const [status, setStatus] = useState('');

  const save = async () => {
    setStatus('');
    try {
      await api.post('/api/fear-greed', { value });
      setStatus('Saved ✓ — will show on tomorrow’s stats');
      onSaved();
    } catch (e) {
      setStatus(String(e));
    }
  };

  return (
    <div>
      <Gauge value={value} label="Fear & Greed" />
      <label className="field" style={{ marginTop: 12 }}>
        <span>Index value: {value}</span>
        <input
          type="range" min={0} max={100} step={1}
          value={value}
          onChange={(e) => setValue(Number(e.target.value))}
          style={{ width: '100%' }}
        />
      </label>
      <button className="primary" onClick={save}>Save Fear &amp; Greed</button>
      {status && <p className={status.startsWith('Saved') ? 'small' : 'error'}>{status}</p>}
    </div>
  );
}
