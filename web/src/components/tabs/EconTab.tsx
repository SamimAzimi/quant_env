import { useEffect, useState } from 'react';
import { api, type Country } from '../../api';

export default function EconTab({ onSaved }: { onSaved: () => void }) {
  const [countries, setCountries] = useState<Country[]>([]);
  const [countryId, setCountryId] = useState('');
  const [newCountry, setNewCountry] = useState('');
  const [addingCountry, setAddingCountry] = useState(false);
  const [name, setName] = useState('');
  const [forecast, setForecast] = useState('');
  const [previous, setPrevious] = useState('');
  const [actual, setActual] = useState('');
  const [outcome, setOutcome] = useState('');
  const [status, setStatus] = useState('');

  const loadCountries = () =>
    api.get<Country[]>('/api/countries').then(setCountries).catch((e) => setStatus(String(e)));

  useEffect(() => { loadCountries(); }, []);

  const addCountry = async () => {
    const n = newCountry.trim();
    if (!n) return;
    const created = await api.post<Country>('/api/countries', { name: n });
    await loadCountries();
    setCountryId(String(created.id));
    setNewCountry('');
    setAddingCountry(false);
  };

  const save = async () => {
    setStatus('');
    try {
      await api.post('/api/econ-reports', {
        name,
        country_id: countryId === '' ? null : Number(countryId),
        forecast, previous,
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
      <label className="field">
        <span>Country</span>
        <div className="row" style={{ flexWrap: 'nowrap' }}>
          <select style={{ flex: 1 }} value={countryId} onChange={(e) => setCountryId(e.target.value)}>
            <option value="">— select —</option>
            {countries.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <button className="ghost" onClick={() => setAddingCountry((v) => !v)}>+</button>
        </div>
      </label>
      {addingCountry && (
        <div className="row" style={{ marginBottom: 10, flexWrap: 'nowrap' }}>
          <input
            style={{ flex: 1 }}
            value={newCountry}
            placeholder="New country name"
            onChange={(e) => setNewCountry(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && addCountry()}
          />
          <button className="primary" disabled={!newCountry.trim()} onClick={addCountry}>
            Add
          </button>
        </div>
      )}
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
