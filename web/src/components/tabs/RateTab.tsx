import { useState } from 'react';
import { api } from '../../api';

const EXAMPLE = `| Meeting Date | 325-350 | 350-375 | 375-400 |
| ------------ | ------- | ------- | ------- |
| 29/04/2026   | 0.0%    | 93.8%   | 6.2%    |`;

export default function RateTab({ onSaved }: { onSaved: () => void }) {
  const [table, setTable] = useState('');
  const [status, setStatus] = useState('');

  const save = async () => {
    setStatus('');
    try {
      const snap = await api.post<{ probs: unknown[] }>('/api/rate-probs', { table });
      setTable('');
      setStatus(`Saved ✓ (${snap.probs.length} probabilities parsed)`);
      onSaved();
    } catch (e) {
      setStatus(String(e));
    }
  };

  return (
    <div>
      <label className="field">
        <span>Paste the FedWatch-style markdown table (dates DD/MM/YYYY, buckets in bps)</span>
        <textarea
          rows={10}
          value={table}
          onChange={(e) => setTable(e.target.value)}
          placeholder={EXAMPLE}
          style={{ fontFamily: 'monospace', fontSize: 12 }}
        />
      </label>
      <button className="primary" disabled={!table.trim()} onClick={save}>Parse &amp; save</button>
      {status && <p className={status.startsWith('Saved') ? 'small' : 'error'}>{status}</p>}
    </div>
  );
}
