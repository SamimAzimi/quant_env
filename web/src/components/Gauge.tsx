interface Props {
  value: number;        // 0..100
  label: string;
  sublabel?: string;
}

const ZONES = [
  { to: 25, color: '#ef5350', name: 'Extreme Fear' },
  { to: 45, color: '#f0842c', name: 'Fear' },
  { to: 55, color: '#f0b429', name: 'Neutral' },
  { to: 75, color: '#9ccc65', name: 'Greed' },
  { to: 100, color: '#26a69a', name: 'Extreme Greed' },
];

const polar = (cx: number, cy: number, r: number, deg: number) => {
  const rad = ((deg - 180) * Math.PI) / 180;
  return [cx + r * Math.cos(rad), cy + r * Math.sin(rad)];
};

/** Ammeter-style semicircular gauge for Fear & Greed. */
export default function Gauge({ value, label, sublabel }: Props) {
  const v = Math.max(0, Math.min(100, value));
  const zone = ZONES.find((z) => v <= z.to) ?? ZONES[ZONES.length - 1];
  const cx = 100, cy = 95, rOut = 84, rIn = 62;

  let from = 0;
  const arcs = ZONES.map((z) => {
    const a0 = (from / 100) * 180;
    const a1 = (z.to / 100) * 180;
    from = z.to;
    const [x0o, y0o] = polar(cx, cy, rOut, a0);
    const [x1o, y1o] = polar(cx, cy, rOut, a1);
    const [x1i, y1i] = polar(cx, cy, rIn, a1);
    const [x0i, y0i] = polar(cx, cy, rIn, a0);
    return {
      color: z.color,
      d: `M ${x0o} ${y0o} A ${rOut} ${rOut} 0 0 1 ${x1o} ${y1o}
          L ${x1i} ${y1i} A ${rIn} ${rIn} 0 0 0 ${x0i} ${y0i} Z`,
    };
  });

  const needleAngle = (v / 100) * 180;
  const [nx, ny] = polar(cx, cy, rOut - 6, needleAngle);

  return (
    <div className="gauge-wrap">
      <svg viewBox="0 0 200 110" width="220" height="121">
        {arcs.map((a, i) => (
          <path key={i} d={a.d} fill={a.color} opacity={0.85} />
        ))}
        <line x1={cx} y1={cy} x2={nx} y2={ny} stroke="#e6e9ef" strokeWidth={3} strokeLinecap="round" />
        <circle cx={cx} cy={cy} r={6} fill="#e6e9ef" />
      </svg>
      <div className="gauge-value" style={{ color: zone.color }}>{Math.round(v)}</div>
      <div className="gauge-label">{zone.name} · {label}</div>
      {sublabel && <div className="gauge-label small">{sublabel}</div>}
    </div>
  );
}
