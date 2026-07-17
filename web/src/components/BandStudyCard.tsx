import { useState } from 'react';
import type { BandPair, BandTest } from '../api';

const pct = (x: number | null | undefined, d = 1) =>
  x === null || x === undefined ? '—' : `${(x * 100).toFixed(d)}%`;
const num = (x: number | null | undefined, d = 2) =>
  x === null || x === undefined ? '—' : x.toFixed(d);

// band index (0..33) → short σ label of its lower edge
function bandTick(i: number, step: number, max: number): string {
  if (i === 0) return `<−${max}`;
  const lo = -max + (i - 1) * step;
  return i === 33 ? `>+${max}` : `${lo >= 0 ? '+' : ''}${lo.toFixed(2)}`;
}

function Histogram({ pair, labels }: { pair: BandPair; labels: string[] }) {
  const probs = pair.A!.probs;
  const exp = pair.A!.expected_probs;
  const W = 680, H = 150, pad = 4;
  const n = probs.length;
  const bw = (W - 2 * pad) / n;
  const maxP = Math.max(...probs, ...exp, 1e-9);
  return (
    <svg viewBox={`0 0 ${W} ${H + 16}`} width="100%">
      {probs.map((p, i) => (
        <rect key={i} x={pad + i * bw + 0.5} y={H - (p / maxP) * (H - 8)}
          width={Math.max(bw - 1, 0.5)} height={(p / maxP) * (H - 8)}
          fill="rgba(79,143,247,0.6)">
          <title>{labels[i]}: {pct(p, 2)} (normal: {pct(exp[i], 2)})</title>
        </rect>
      ))}
      <polyline fill="none" stroke="#f0b429" strokeWidth={1.4}
        points={exp.map((p, i) =>
          `${pad + i * bw + bw / 2},${H - (p / maxP) * (H - 8)}`).join(' ')} />
      {[0, 9, 17, 25, 33].map((i) => (
        <text key={i} x={pad + i * bw + bw / 2} y={H + 12} fontSize={9}
          fill="#8b93a3" textAnchor="middle">{bandTick(i, 0.25, 4)}</text>
      ))}
    </svg>
  );
}

const KEY_BANDS = [
  { idx: 19, label: '+0.5σ' }, { idx: 21, label: '+1σ' }, { idx: 25, label: '+2σ' },
  { idx: 29, label: '+3σ' }, { idx: 33, label: '+4σ' },
  { idx: 14, label: '−0.5σ' }, { idx: 12, label: '−1σ' }, { idx: 8, label: '−2σ' },
  { idx: 4, label: '−3σ' }, { idx: 0, label: '−4σ' },
];
const CURVE_COLORS = ['#26a69a', '#4f8ff7', '#ab47bc', '#f0842c', '#ef5350',
  '#8d6e63', '#5ec8f0', '#c9c95e', '#e57373', '#81c784'];

function Survival({ pair }: { pair: BandPair }) {
  const rows = pair.B_C!;
  const W = 680, H = 160, padL = 28, padB = 16;
  const horizon = Math.max(...KEY_BANDS.map((k) => rows[k.idx]?.survival.length ?? 0), 2) - 1;
  const x = (i: number) => padL + (i / horizon) * (W - padL - 8);
  const y = (s: number) => 4 + (1 - s) * (H - padB - 8);
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%">
        {[0, 0.5, 1].map((g) => (
          <g key={g}>
            <line x1={padL} y1={y(g)} x2={W - 8} y2={y(g)} stroke="#232a38" />
            <text x={2} y={y(g) + 3} fontSize={9} fill="#8b93a3">{g}</text>
          </g>
        ))}
        {KEY_BANDS.map((k, ci) => {
          const s = rows[k.idx]?.survival;
          if (!s || s.length < 2) return null;
          return (
            <polyline key={k.idx} fill="none"
              stroke={CURVE_COLORS[ci % CURVE_COLORS.length]} strokeWidth={1.6}
              points={s.map((v, i) => `${x(i)},${y(v)}`).join(' ')} />
          );
        })}
        <text x={W / 2} y={H - 2} fontSize={9} fill="#8b93a3" textAnchor="middle">
          candles into trigger session → S(n) = P(not yet touched)
        </text>
      </svg>
      <div className="row small">
        {KEY_BANDS.map((k, ci) => (
          <span key={k.idx} className="muted">
            <span className="legend-dot" style={{ background: CURVE_COLORS[ci % CURVE_COLORS.length] }} />
            {k.label} ({pct(pair.B_C![k.idx]?.touch_rate, 0)} touch)
          </span>
        ))}
      </div>
    </div>
  );
}

function Heatmap({ pair }: { pair: BandPair }) {
  const M = pair.D!.matrix;
  const n = M.length;
  const cell = 12;
  const maxV = Math.max(...M.flat(), 1e-9);
  return (
    <div style={{ overflowX: 'auto' }}>
      <svg width={n * cell + 40} height={n * cell + 20}>
        {M.map((row, i) => row.map((v, j) => (
          <rect key={`${i}-${j}`} x={30 + j * cell} y={i * cell}
            width={cell - 1} height={cell - 1}
            fill={`rgba(79,143,247,${Math.min(v / maxV, 1) * 0.95 + 0.03})`}>
            <title>P({bandTick(i, 0.25, 4)} → {bandTick(j, 0.25, 4)}) = {pct(v, 1)}</title>
          </rect>
        )))}
        {[0, 9, 17, 25, 33].map((i) => (
          <g key={i}>
            <text x={26} y={i * cell + 9} fontSize={8} fill="#8b93a3" textAnchor="end">
              {bandTick(i, 0.25, 4)}
            </text>
            <text x={30 + i * cell + 5} y={n * cell + 12} fontSize={8} fill="#8b93a3"
              textAnchor="middle">{bandTick(i, 0.25, 4)}</text>
          </g>
        ))}
      </svg>
      <p className="small muted">rows = current band, columns = next candle's band (row-normalised)</p>
    </div>
  );
}

function TestsTable({ tests }: { tests: BandTest[] }) {
  return (
    <table className="data">
      <thead><tr><th>Test</th><th>H₀</th><th>stat</th><th>p</th><th>Reading</th></tr></thead>
      <tbody>
        {tests.map((t) => {
          const rejected = (t.p_value !== null && t.p_value < 0.05) || t.reject_5pct;
          return (
            <tr key={t.name}>
              <td>{t.name}</td>
              <td className="small muted">{t.null}</td>
              <td>{num(t.statistic, 3)}</td>
              <td className={rejected ? 'outcome-miss' : ''}>
                {t.p_value !== null ? t.p_value.toExponential(1)
                  : `crit ${num(t.crit_5pct)}`}
              </td>
              <td className="small">{t.interpretation}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/** One session pair's full A–G band-behaviour study, tabbed. */
export default function BandStudyCard({ pair, labels }: { pair: BandPair; labels: string[] }) {
  const TABS = ['Distribution', 'Survival', 'Path geometry', 'Transitions',
    'Escape', 'Tests'] as const;
  const [tab, setTab] = useState<(typeof TABS)[number]>('Distribution');

  if (pair.note) {
    return (
      <div className="card">
        <h2>{pair.analyze} → {pair.trigger}</h2>
        <p className="muted small">{pair.note}</p>
      </div>
    );
  }
  const verdictCol = pair.G!.verdict === 'structured' ? 'var(--green)'
    : pair.G!.verdict === 'mixed' ? 'var(--amber)' : 'var(--muted)';
  const keyRows = pair.B_C!.filter((r) => r.n_touch > 0
    && KEY_BANDS.some((k) => k.idx === r.band));

  return (
    <div className="card">
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <h2>{pair.analyze} → {pair.trigger}</h2>
        <span className="small">
          <span className="chip" style={{ borderColor: verdictCol, color: verdictCol }}>
            {pair.G!.verdict} ({pair.G!.n_rejections}/{pair.G!.n_tests} tests reject noise)
          </span>{' '}
          <span className="muted">{pair.n_days}d · {pair.n_candles} candles</span>
        </span>
      </div>
      <div className="tabbar">
        {TABS.map((t) => (
          <button key={t} className={t === tab ? 'active' : ''} onClick={() => setTab(t)}>{t}</button>
        ))}
      </div>
      <div style={{ paddingTop: 10 }}>
        {tab === 'Distribution' && (
          <>
            <p className="small muted">
              Trigger-session closes across the analyze session's 0.25σ bands
              (bars) vs the normal-model expectation (amber line).
            </p>
            <Histogram pair={pair} labels={labels} />
          </>
        )}
        {tab === 'Survival' && <Survival pair={pair} />}
        {tab === 'Path geometry' && (
          <table className="data">
            <thead><tr>
              <th>Band</th><th>touch</th><th>med. touch</th><th>candles→touch</th>
              <th>adverse (bands)</th><th>oscillation</th><th>candles inside</th>
            </tr></thead>
            <tbody>
              {keyRows.map((r) => (
                <tr key={r.band}>
                  <td>{KEY_BANDS.find((k) => k.idx === r.band)?.label}</td>
                  <td>{pct(r.touch_rate, 0)}</td>
                  <td>{num(r.median_touch, 0)}</td>
                  <td>{num(r.candles_to_touch_mean, 1)}</td>
                  <td>{num(r.adverse_bands_mean, 1)}</td>
                  <td>{pct(r.oscillation_mean, 0)}</td>
                  <td>{num(r.candles_inside_mean, 1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {tab === 'Transitions' && <Heatmap pair={pair} />}
        {tab === 'Escape' && (
          <table className="data">
            <thead><tr>
              <th>Band</th><th>exits</th><th>Δbands (signed)</th>
              <th>|Δbands|</th><th>toward centre</th>
            </tr></thead>
            <tbody>
              {pair.E!.filter((e) => e.n_exits >= 10
                && KEY_BANDS.some((k) => k.idx === e.band)).map((e) => (
                <tr key={e.band}>
                  <td>{KEY_BANDS.find((k) => k.idx === e.band)?.label}</td>
                  <td>{e.n_exits}</td>
                  <td>{num(e.mean_signed_bands)}</td>
                  <td>{num(e.mean_abs_bands)}</td>
                  <td>{pct(e.toward_center_share, 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {tab === 'Tests' && <TestsTable tests={pair.F!} />}
      </div>
    </div>
  );
}
