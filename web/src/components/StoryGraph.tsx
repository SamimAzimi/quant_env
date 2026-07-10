import type { NewsGroup, NewsItem } from '../api';

interface Props {
  group: NewsGroup;
  onSelect: (n: NewsItem) => void;
  selectedId?: number;
}

const ROLE_COLORS: Record<string, string> = {
  primary: '#4f8ff7', supporting: '#26a69a', contradicting: '#ef5350',
  duplicate: '#8b93a3', update: '#f0b429',
};

/**
 * Simple layered DAG rendering of one story group: columns are generations
 * (BFS depth from the root stories), edges connect parent → child.
 * Nodes are clickable to show the story's details.
 */
export default function StoryGraph({ group, onSelect, selectedId }: Props) {
  const ids = group.news.map((n) => n.id);
  const byId = new Map(group.news.map((n) => [n.id, n]));
  const children = new Map<number, number[]>();
  const hasParent = new Set<number>();
  for (const [p, c] of group.edges) {
    children.set(p, [...(children.get(p) ?? []), c]);
    hasParent.add(c);
  }

  // BFS depth from roots
  const depth = new Map<number, number>();
  const queue: [number, number][] =
    ids.filter((id) => !hasParent.has(id)).map((id) => [id, 0]);
  while (queue.length) {
    const [id, d] = queue.shift()!;
    if (depth.has(id) && depth.get(id)! >= d) continue;
    depth.set(id, d);
    for (const c of children.get(id) ?? []) queue.push([c, d + 1]);
  }
  ids.forEach((id) => { if (!depth.has(id)) depth.set(id, 0); });

  const cols = new Map<number, number[]>();
  for (const id of ids) {
    const d = depth.get(id)!;
    cols.set(d, [...(cols.get(d) ?? []), id]);
  }
  const colW = 190, rowH = 64, r = 9;
  const nCols = cols.size;
  const maxRows = Math.max(...[...cols.values()].map((c) => c.length));
  const width = Math.max(nCols * colW, 200);
  const height = Math.max(maxRows * rowH, 90);

  const pos = new Map<number, { x: number; y: number }>();
  for (const [d, colIds] of cols) {
    colIds
      .sort((a, b) => byId.get(a)!.publish_time.localeCompare(byId.get(b)!.publish_time))
      .forEach((id, i) => {
        pos.set(id, { x: d * colW + 70, y: i * rowH + 36 });
      });
  }

  return (
    <div style={{ overflowX: 'auto' }}>
      <svg width={width} height={height}>
        {group.edges.map(([p, c]) => {
          const a = pos.get(p); const b = pos.get(c);
          if (!a || !b) return null;
          return (
            <line key={`${p}-${c}`} x1={a.x + r} y1={a.y} x2={b.x - r} y2={b.y}
              stroke="#2a3140" strokeWidth={1.5} />
          );
        })}
        {ids.map((id) => {
          const n = byId.get(id)!;
          const p = pos.get(id)!;
          return (
            <g key={id} style={{ cursor: 'pointer' }} onClick={() => onSelect(n)}>
              <circle cx={p.x} cy={p.y} r={r}
                fill={ROLE_COLORS[n.role] ?? '#8b93a3'}
                stroke={selectedId === id ? '#e6e9ef' : 'transparent'}
                strokeWidth={2} />
              <text x={p.x + r + 5} y={p.y + 4} fill="#8b93a3" fontSize={11}>
                {n.title.slice(0, 22)}{n.title.length > 22 ? '…' : ''}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
