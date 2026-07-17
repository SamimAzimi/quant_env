import type { DistStats } from '../api';

const pct = (x: number) => `${(x * 100).toFixed(2)}%`;
const KS = [0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4];

/**
 * SVG histogram of a segment's log-return distribution with the mean and
 * ±0.5σ…±4σ band lines overlaid. Returns are on a % axis. Lines outside
 * the histogram range are simply not drawn.
 */
export default function DistHistogram({ dist, title }: { dist: DistStats; title: string }) {
  if (dist.note || !dist.hist || dist.mean === undefined || dist.std === undefined) {
    return (
      <div className="chart-box">
        <h3>{title}</h3>
        <p className="muted small">{dist.note ?? 'No distribution.'}</p>
      </div>
    );
  }
  const { edges, counts } = dist.hist;
  const mu = dist.mean, sd = dist.std;
  const W = 320, H = 150, padB = 20, padL = 4;
  const lo = edges[0], hi = edges[edges.length - 1];
  const span = hi - lo || 1;
  const maxC = Math.max(...counts, 1);
  const x = (v: number) => padL + ((v - lo) / span) * (W - 2 * padL);
  const barW = (W - 2 * padL) / counts.length;

  const line = (v: number, color: string, dash: boolean) =>
    v < lo || v > hi ? null : (
      <line x1={x(v)} y1={0} x2={x(v)} y2={H - padB}
        stroke={color} strokeWidth={1.1} strokeDasharray={dash ? '3 3' : undefined} />
    );

  return (
    <div className="chart-box">
      <h3>{title} <span className="muted small">n={dist.n}</span></h3>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ maxHeight: 165 }}>
        {counts.map((c, i) => {
          const h = (c / maxC) * (H - padB - 6);
          return (
            <rect key={i} x={padL + i * barW + 0.5} y={H - padB - h}
              width={Math.max(barW - 1, 0.5)} height={h} fill="rgba(79,143,247,0.5)" />
          );
        })}
        {KS.map((k) => (
          <g key={k}>
            {line(mu + k * sd, '#26a69a', k % 2 !== 0)}
            {line(mu - k * sd, '#ef5350', k % 2 !== 0)}
          </g>
        ))}
        {line(mu, '#e6e9ef', false)}
      </svg>
      <div className="row small muted" style={{ gap: 10, flexWrap: 'wrap', marginTop: 4 }}>
        <span>μ {pct(mu)}</span>
        <span>σ {pct(sd)}</span>
        <span>skew {dist.skew?.toFixed(2)}</span>
        {dist.probs && <span>P(&gt;0) {(dist.probs.p_up * 100).toFixed(0)}%</span>}
        {dist.probs && (
          <span>
            &gt;+1σ {(dist.probs.up['1.0'] * 100).toFixed(0)}% ·
            &lt;−1σ {(dist.probs.down['1.0'] * 100).toFixed(0)}%
          </span>
        )}
      </div>
    </div>
  );
}
