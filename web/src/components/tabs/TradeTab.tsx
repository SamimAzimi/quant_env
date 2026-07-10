import { useEffect, useState } from 'react';
import { api, type AssetCategory } from '../../api';
import UtcDateTimeInput from './UtcDateTimeInput';

export default function TradeTab({ onSaved }: { onSaved: () => void }) {
  const [categories, setCategories] = useState<AssetCategory[]>([]);
  const [assetId, setAssetId] = useState('');
  const [entryTime, setEntryTime] = useState('');
  const [exitTime, setExitTime] = useState('');
  const [entryPrice, setEntryPrice] = useState('');
  const [exitPrice, setExitPrice] = useState('');
  const [entryReason, setEntryReason] = useState('');
  const [exitReason, setExitReason] = useState('');
  const [tp, setTp] = useState('');
  const [sl, setSl] = useState('');
  const [remarks, setRemarks] = useState('');
  const [status, setStatus] = useState('');

  useEffect(() => {
    api.get<AssetCategory[]>('/api/effects')
      .then(setCategories)
      .catch((e) => setStatus(String(e)));
  }, []);

  const save = async () => {
    setStatus('');
    try {
      await api.post('/api/trades', {
        asset_id: assetId === '' ? null : Number(assetId),
        entry_time: entryTime,
        exit_time: exitTime || null,
        entry_price: entryPrice === '' ? null : Number(entryPrice),
        exit_price: exitPrice === '' ? null : Number(exitPrice),
        entry_reason: entryReason,
        exit_reason: exitReason || null,
        tp: tp === '' ? null : Number(tp),
        sl: sl === '' ? null : Number(sl),
        remarks,
      });
      setAssetId(''); setEntryTime(''); setExitTime(''); setEntryPrice('');
      setExitPrice(''); setEntryReason(''); setExitReason('');
      setTp(''); setSl(''); setRemarks('');
      setStatus('Saved ✓');
      onSaved();
    } catch (e) {
      setStatus(String(e));
    }
  };

  return (
    <div>
      <label className="field">
        <span>Asset</span>
        <select value={assetId} onChange={(e) => setAssetId(e.target.value)}>
          <option value="">— select ticker —</option>
          {categories.map((c) => (
            <optgroup key={c.id} label={`${c.kind === 'hard' ? 'Hard' : 'Soft'} · ${c.name}`}>
              {c.assets.map((a) => (
                <option key={a.id} value={a.id}>{a.ticker}</option>
              ))}
            </optgroup>
          ))}
        </select>
      </label>
      <UtcDateTimeInput label="Entry Time (UTC)" value={entryTime} onChange={setEntryTime} />
      <UtcDateTimeInput label="Exit Time (UTC) — optional, can be added later" value={exitTime} onChange={setExitTime} />
      <div className="row">
        <label className="field" style={{ flex: 1 }}>
          <span>Entry Price</span>
          <input type="number" step="any" value={entryPrice} onChange={(e) => setEntryPrice(e.target.value)} />
        </label>
        <label className="field" style={{ flex: 1 }}>
          <span>Exit Price — optional</span>
          <input type="number" step="any" value={exitPrice} onChange={(e) => setExitPrice(e.target.value)} />
        </label>
      </div>
      <label className="field">
        <span>Entry Reason</span>
        <textarea rows={2} value={entryReason} onChange={(e) => setEntryReason(e.target.value)} />
      </label>
      <label className="field">
        <span>Exit Reason — optional</span>
        <textarea rows={2} value={exitReason} onChange={(e) => setExitReason(e.target.value)} />
      </label>
      <div className="row">
        <label className="field" style={{ flex: 1 }}>
          <span>TP</span>
          <input type="number" step="any" value={tp} onChange={(e) => setTp(e.target.value)} />
        </label>
        <label className="field" style={{ flex: 1 }}>
          <span>SL</span>
          <input type="number" step="any" value={sl} onChange={(e) => setSl(e.target.value)} />
        </label>
      </div>
      <label className="field">
        <span>Remarks</span>
        <textarea rows={2} value={remarks} onChange={(e) => setRemarks(e.target.value)} />
      </label>
      <button className="primary" disabled={!entryTime} onClick={save}>Save trade</button>
      {status && <p className={status.startsWith('Saved') ? 'small' : 'error'}>{status}</p>}
    </div>
  );
}
