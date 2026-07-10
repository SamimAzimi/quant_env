import { useState } from 'react';
import { api } from '../../api';
import UtcDateTimeInput from './UtcDateTimeInput';

export default function TradeTab({ onSaved }: { onSaved: () => void }) {
  const [entryTime, setEntryTime] = useState('');
  const [exitTime, setExitTime] = useState('');
  const [entryReason, setEntryReason] = useState('');
  const [exitReason, setExitReason] = useState('');
  const [tp, setTp] = useState('');
  const [sl, setSl] = useState('');
  const [remarks, setRemarks] = useState('');
  const [status, setStatus] = useState('');

  const save = async () => {
    setStatus('');
    try {
      await api.post('/api/trades', {
        entry_time: entryTime,
        exit_time: exitTime || null,
        entry_reason: entryReason,
        exit_reason: exitReason || null,
        tp: tp === '' ? null : Number(tp),
        sl: sl === '' ? null : Number(sl),
        remarks,
      });
      setEntryTime(''); setExitTime(''); setEntryReason(''); setExitReason('');
      setTp(''); setSl(''); setRemarks('');
      setStatus('Saved ✓');
      onSaved();
    } catch (e) {
      setStatus(String(e));
    }
  };

  return (
    <div>
      <UtcDateTimeInput label="Entry Time (UTC)" value={entryTime} onChange={setEntryTime} />
      <UtcDateTimeInput label="Exit Time (UTC) — optional, can be added later" value={exitTime} onChange={setExitTime} />
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
