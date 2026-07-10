import { useState } from 'react';
import { api } from '../../api';

export default function ThoughtsTab({ onSaved }: { onSaved: () => void }) {
  const [body, setBody] = useState('');
  const [status, setStatus] = useState('');

  const save = async () => {
    setStatus('');
    try {
      await api.post('/api/thoughts', { body });
      setBody('');
      setStatus('Saved ✓ (timestamped now, UTC)');
      onSaved();
    } catch (e) {
      setStatus(String(e));
    }
  };

  return (
    <div>
      <label className="field">
        <span>Analyze & Thoughts — timestamped at save time</span>
        <textarea
          rows={6}
          value={body}
          onChange={(e) => setBody(e.target.value)}
          placeholder="What are you seeing right now?"
        />
      </label>
      <button className="primary" disabled={!body.trim()} onClick={save}>Save thought</button>
      {status && <p className={status.startsWith('Saved') ? 'small' : 'error'}>{status}</p>}
    </div>
  );
}
