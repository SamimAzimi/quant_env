import { useState } from 'react';
import type { RateSnapshot } from '../api';

interface Props {
  today: RateSnapshot | null;
  previous: RateSnapshot | null;
}

const TOP_N = 3;

/**
 * Grouped horizontal bars: per meeting, probability by rate bucket.
 * Only the top three buckets show by default — "see more…" reveals the
 * rest. The previous day's value appears as a marker on each bar.
 */
export default function RateProbChart({ today, previous }: Props) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  if (!today) return <p className="muted">No rate table recorded yet. Use Record → FOMC.</p>;

  const toggle = (meeting: string) =>
    setExpanded((s) => {
      const next = new Set(s);
      if (next.has(meeting)) next.delete(meeting); else next.add(meeting);
      return next;
    });

  const meetings = [...new Set(today.probs.map((p) => p.meeting_date))].sort();
  const prevMap = new Map(
    (previous?.probs ?? []).map((p) => [`${p.meeting_date}|${p.bucket}`, p.probability]),
  );

  return (
    <div>
      {meetings.map((meeting) => {
        const all = today.probs
          .filter((p) => p.meeting_date === meeting && p.probability > 0.05)
          .sort((a, b) => b.probability - a.probability);
        if (all.length === 0) return null;
        const isOpen = expanded.has(meeting);
        const rows = isOpen ? all : all.slice(0, TOP_N);
        const hidden = all.length - rows.length;
        return (
          <div key={meeting} style={{ marginBottom: 14 }}>
            <div className="small" style={{ marginBottom: 4 }}>
              <strong>{new Date(meeting).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })}</strong>
            </div>
            {rows.map((p) => {
              const prev = prevMap.get(`${p.meeting_date}|${p.bucket}`);
              return (
                <div key={p.bucket} className="row small" style={{ marginBottom: 3, flexWrap: 'nowrap' }}>
                  <span style={{ width: 66, flexShrink: 0 }} className="muted">{p.bucket}</span>
                  <div style={{ flex: 1, position: 'relative', height: 16, background: '#232a38', borderRadius: 4 }}>
                    <div
                      style={{
                        width: `${p.probability}%`, height: '100%',
                        background: '#4f8ff7', borderRadius: 4,
                      }}
                    />
                    {prev !== undefined && (
                      <div
                        title={`Previous day: ${prev.toFixed(1)}%`}
                        style={{
                          position: 'absolute', top: -2, bottom: -2,
                          left: `calc(${Math.min(prev, 100)}% - 1px)`,
                          width: 2, background: '#f0b429',
                        }}
                      />
                    )}
                  </div>
                  <span style={{ width: 52, textAlign: 'right', flexShrink: 0 }}>
                    {p.probability.toFixed(1)}%
                  </span>
                </div>
              );
            })}
            {(hidden > 0 || isOpen) && (
              <button className="seemore" onClick={() => toggle(meeting)}>
                {isOpen ? 'see less' : `see more… (${hidden})`}
              </button>
            )}
          </div>
        );
      })}
      {previous && (
        <div className="small muted">
          <span className="legend-dot" style={{ background: '#f0b429' }} />
          previous day marker
        </div>
      )}
    </div>
  );
}
