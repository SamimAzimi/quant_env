import type { DistStats } from '../api';

const pct = (x: number) => `${(x * 100).toFixed(2)}%`;

/**
 * SVG histogram of a session/daily log-return distribution with the mean
 * and ±1σ / ±2σ band lines overlaid. Returns are shown on a % axis.
 */
export default function DistHistogram({ dist, title }: { dist: DistStats; title: string }) {
  if (dist.note || !dist.hist || !dist.bands || dist.mean === undefined) {
    return (
      <div className="chart-box">
        <h3>{title}</h3>
        <p className="muted small">{dist.note ?? 'No distribution.'}</p>
      </div>
    );
  }
  const { edges, counts } = dist.hist;
  const { up1, up2, dn1, dn2 } = dist.bands;
  const W = 320, H = 150, padB = 22, padL = 4;
  const lo = edges[0];
  const hi = edges[edges.length - 1];
  const span = hi - lo || 1;
  const maxC = Math.max(...counts, 1);
  const x = (v: number) => padL + ((v - lo) / span) * (W - 2 * padL);
  const barW = (W - 2 * padL) / counts.length;

  const line = (v: number, color: string, label: string, dash = false) => {
    if (v < lo || v > hi) return null;
    return (
      <g key={label}>
        <line x1={x(v)} y1={0} x2={x(v)} y2={H - padB}
          stroke={color} strokeWidth={1.4} strokeDasharray={dash ? '4 3' : undefined} />
        <text x={x(v)} y={H - padB + 12} fontSize={9} fill={color} textAnchor="middle">
          {label}
        </text>
      </g>
    );
  };

  return (
    <div className="chart-box">
      <h3>{title} <span className="muted small">n={dist.n}</span></h3>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ maxHeight: 170 }}>
        {counts.map((c, i) => {
          const h = (c / maxC) * (H - padB - 6);
          return (
            <rect key={i} x={padL + i * barW + 0.5} y={H - padB - h}
              width={Math.max(barW - 1, 0.5)} height={h}
              fill="rgba(79,143,247,0.5)" />
          );
        })}
        {line(dist.mean, '#e6e9ef', 'μ')}
        {line(up1, '#26a69a', '+1σ', true)}
        {line(up2, '#26a69a', '+2σ')}
        {line(dn1, '#ef5350', '−1σ', true)}
        {line(dn2, '#ef5350', '−2σ')}
      </svg>
      <div className="row small muted" style={{ gap: 12, flexWrap: 'wrap', marginTop: 4 }}>
        <span>μ {pct(dist.mean)}</span>
        <span>σ {pct(dist.std ?? 0)}</span>
        <span>skew {dist.skew?.toFixed(2)}</span>
        {dist.probs && <span>P(&gt;0) {(dist.probs.p_up * 100).toFixed(0)}%</span>}
        {dist.probs && (
          <span>
            tails: {(dist.probs.p_gt_1sd * 100).toFixed(0)}% &gt;+1σ ·{' '}
            {(dist.probs.p_lt_1sd * 100).toFixed(0)}% &lt;−1σ
          </span>
        )}
      </div>
    </div>
  );
}
