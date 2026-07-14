import type { SideStats, Transition } from '../api';

const pctOrDash = (x: number | null | undefined) =>
  x === null || x === undefined ? '—' : `${(x * 100).toFixed(1)}%`;

function ProbBar({ label, value, color }: { label: string; value: number | null; color: string }) {
  const w = value === null ? 0 : Math.min(value * 100, 100);
  return (
    <div className="row small" style={{ flexWrap: 'nowrap', margin: '2px 0' }}>
      <span style={{ width: 128, flexShrink: 0 }} className="muted">{label}</span>
      <div style={{ flex: 1, height: 14, background: '#232a38', borderRadius: 4 }}>
        <div style={{ width: `${w}%`, height: '100%', background: color, borderRadius: 4 }} />
      </div>
      <span style={{ width: 48, textAlign: 'right', flexShrink: 0 }}>{pctOrDash(value)}</span>
    </div>
  );
}

function Side({ side, dir, color }: { side: SideStats; dir: string; color: string }) {
  return (
    <div style={{ flex: 1, minWidth: 240 }}>
      <div className="small" style={{ fontWeight: 600, marginBottom: 4 }}>{dir}</div>
      <ProbBar label="P(breakout ±1σ)" value={side.p_breakout} color={color} />
      <ProbBar label="P(reach ±2σ)" value={side.p_target} color={color} />
      <ProbBar label="P(2σ | breakout)" value={side.p_target_given_breakout} color="#f0b429" />
      <div className="small muted" style={{ marginTop: 4 }}>
        Clean move (n={side.clean.n}):{' '}
        {side.clean.eff_mean !== null
          ? <>efficiency {(side.clean.eff_mean * 100).toFixed(0)}% ·{' '}
              adverse {side.clean.mae_sd_mean?.toFixed(2)}σ ·{' '}
              {side.clean.bars_mean?.toFixed(1)} bars</>
          : 'no qualifying moves'}
      </div>
    </div>
  );
}

/**
 * One reference→trigger session pair: the conditional-continuation
 * probabilities and clean-move quality, up and down.
 */
export default function TransitionCard({ t }: { t: Transition }) {
  const title = `${t.reference} → ${t.trigger}${t.overnight ? ' (overnight)' : ''}`;
  if (t.note || !t.up || !t.down) {
    return (
      <div className="card">
        <h2>{title}</h2>
        <p className="muted small">{t.note ?? 'Not enough data.'}</p>
      </div>
    );
  }
  return (
    <div className="card">
      <h2>{title}</h2>
      <p className="small muted">
        {t.reference} reference bands: μ {(t.ref_mean! * 100).toFixed(2)}% ·
        σ {(t.ref_std! * 100).toFixed(2)}%. Does {t.trigger} close beyond ±1σ
        and reach {t.reference}'s ±2σ?
      </p>
      <div className="row" style={{ gap: 18, alignItems: 'flex-start' }}>
        <Side side={t.up} dir="▲ Upside" color="#26a69a" />
        <Side side={t.down} dir="▼ Downside" color="#ef5350" />
      </div>
    </div>
  );
}
