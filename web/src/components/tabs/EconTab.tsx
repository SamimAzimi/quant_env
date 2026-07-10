import { useState } from 'react';
import { api } from '../../api';

export default function EconTab({ onSaved }: { onSaved: () => void }) {
  const [name, setName] = useState('');
  const [forecast, setForecast] = useState('');
  const [previous, setPrevious] = useState('');
  const [actual, setActual] = useState('');
  const [outcome, setOutcome] = useState('');
  const [status, setStatus] = useState('');

  const save = async () => {
    setStatus('');
    try {
      await api.post('/api/econ-reports', {
        name, forecast, previous,
        actual: actual || null,
        outcome: outcome || null,
      });
      setName(''); setForecast(''); setPrevious(''); setActual(''); setOutcome('');
      setStatus('Saved ✓');
      onSaved();
    } catch (e) {
      setStatus(String(e));
    }
  };

  return (
    <div>
      <label className="field">
        <span>Report Name</span>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. CPI YoY" />
      </label>
      <div className="row">
        <label className="field" style={{ flex: 1 }}>
          <span>Forecast</span>
          <input value={forecast} onChange={(e) => setForecast(e.target.value)} />
        </label>
        <label className="field" style={{ flex: 1 }}>
          <span>Previous</span>
          <input value={previous} onChange={(e) => setPrevious(e.target.value)} />
        </label>
      </div>
      <div className="row">
        <label className="field" style={{ flex: 1 }}>
          <span>Actual — leave empty until released</span>
          <input value={actual} onChange={(e) => setActual(e.target.value)} />
        </label>
        <label className="field" style={{ flex: 1 }}>
          <span>Beat or Miss</span>
          <select value={outcome} onChange={(e) => setOutcome(e.target.value)}>
            <option value="">—</option>
            <option value="beat">Beat</option>
            <option value="miss">Miss</option>
            <option value="inline">Inline</option>
          </select>
        </label>
      </div>
      <button className="primary" disabled={!name.trim()} onClick={save}>Save report</button>
      {status && <p className={status.startsWith('Saved') ? 'small' : 'error'}>{status}</p>}
    </div>
  );
}
