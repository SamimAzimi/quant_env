import { useState } from 'react';
import type { SideStats, Trigger } from '../api';

const pctOrDash = (x: number | null | undefined) =>
  x === null || x === undefined ? '—' : `${(x * 100).toFixed(0)}%`;

// blue→teal heat for a probability cell
function heat(p: number | null): string {
  if (p === null) return 'transparent';
  const a = 0.12 + 0.6 * Math.min(Math.max(p, 0), 1);
  return `rgba(79,143,247,${a.toFixed(3)})`;
}

function Matrix({ side, bands, selB, selT, onPick }: {
  side: SideStats; bands: number[];
  selB: number; selT: number; onPick: (b: number, t: number) => void;
}) {
  return (
    <table className="data matrix">
      <thead>
        <tr>
          <th className="muted">brk＼tgt</th>
          {bands.map((t, j) => <th key={j}>{t}σ</th>)}
        </tr>
      </thead>
      <tbody>
        {bands.map((b, i) => (
          <tr key={i}>
            <th className="muted">{b}σ <span className="small">({side.breakout_counts[i]})</span></th>
            {bands.map((t, j) => {
              const v = side.matrix[i][j];
              const sel = i === selB && j === selT;
              return (
                <td key={j}
                  title={`P(touch ${t}σ | close beyond ${b}σ)`}
                  onClick={() => onPick(i, j)}
                  style={{
                    background: j < i ? 'transparent' : heat(v),
                    outline: sel ? '2px solid var(--amber)' : undefined,
                    cursor: 'pointer', textAlign: 'center',
                  }}>
                  {j < i ? '' : pctOrDash(v)}
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Clean({ side }: { side: SideStats }) {
  return (
    <div className="small" style={{ marginTop: 6 }}>
      <div className="muted">clean move per segment (eff · adverse · bars · n)</div>
      {side.clean_segments.map((s, i) => (
        <div key={i} className="row" style={{ flexWrap: 'nowrap', gap: 8 }}>
          <span style={{ width: 64 }} className="muted">{s.from}→{s.to}σ</span>
          <div style={{ flex: 1, height: 10, background: '#232a38', borderRadius: 3 }}>
            <div style={{
              width: `${(s.eff_mean ?? 0) * 100}%`, height: '100%',
              background: '#26a69a', borderRadius: 3,
            }} />
          </div>
          <span style={{ width: 130, textAlign: 'right' }}>
            {s.eff_mean !== null
              ? `${(s.eff_mean * 100).toFixed(0)}% · ${s.adverse_mean?.toFixed(2)}σ · ${s.bars_mean?.toFixed(1)} · ${s.n}`
              : '—'}
          </span>
        </div>
      ))}
    </div>
  );
}

function Side({ title, side, bands, selB, selT, onPick }: {
  title: string; side: SideStats; bands: number[];
  selB: number; selT: number; onPick: (b: number, t: number) => void;
}) {
  const cell = side.matrix[selB]?.[selT] ?? null;
  return (
    <div style={{ flex: 1, minWidth: 280 }}>
      <div className="small" style={{ fontWeight: 600, marginBottom: 4 }}>{title}</div>
      <div className="small muted" style={{ marginBottom: 4 }}>
        P(touch <b>{bands[selT]}σ</b> | close beyond <b>{bands[selB]}σ</b>) ={' '}
        <b style={{ color: 'var(--amber)' }}>{pctOrDash(cell)}</b>
        {' '}· breakouts n={side.breakout_counts[selB]}
      </div>
      <Matrix side={side} bands={bands} selB={selB} selT={selT} onPick={onPick} />
      <Clean side={side} />
    </div>
  );
}

/** One reference→trigger card: full breakout×target matrix (selectable cell)
 *  plus per-adjacent-segment clean-move quality, up and down. */
export default function TriggerCard({ trig }: { trig: Trigger }) {
  const bands = trig.up.bands;
  const [selB, setSelB] = useState(1);   // default breakout = 1σ
  const [selT, setSelT] = useState(3);   // default target   = 2σ
  const pick = (b: number, t: number) => { setSelB(b); setSelT(Math.max(t, b)); };

  return (
    <div className="trigger-card">
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <strong className="small">→ {trig.label}{trig.overnight ? ' (overnight)' : ''}</strong>
        <span className="muted small">n={trig.n_days} days</span>
      </div>
      <div className="row" style={{ gap: 20, alignItems: 'flex-start', marginTop: 6 }}>
        <Side title="▲ Upside" side={trig.up} bands={bands}
          selB={selB} selT={selT} onPick={pick} />
        <Side title="▼ Downside" side={trig.down} bands={bands}
          selB={selB} selT={selT} onPick={pick} />
      </div>
    </div>
  );
}
