import { useEffect, useRef } from 'react';
import { ColorType, LineSeries, createChart } from 'lightweight-charts';
import type { ReturnsSeries, SessionSpan } from '../api';
import { addSessionBands } from './sessionBands';

export const SERIES_COLORS = [
  '#4f8ff7', '#f0b429', '#26a69a', '#ef5350', '#ab47bc',
  '#9ccc65', '#f0842c', '#29b6f6', '#ec407a', '#8d6e63',
];

interface Props {
  series: ReturnsSeries[];
  sessions?: SessionSpan[];
}

/** Multi-asset cumulative log-return lines (%) over session backgrounds. */
export default function ReturnsChart({ series, sessions }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;
    const chart = createChart(ref.current, {
      height: 300,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#8b93a3',
      },
      grid: {
        vertLines: { color: '#232a38' },
        horzLines: { color: '#232a38' },
      },
      timeScale: { timeVisible: true, secondsVisible: false },
      rightPriceScale: { borderColor: '#2a3140' },
      autoSize: true,
    });
    if (series.length > 0) {
      // union of all series' timestamps: an index that only trades US hours
      // must not limit where the Sydney/Tokyo/London bands can render
      const times = [...new Set(series.flatMap((s) => s.points.map((p) => p.time)))]
        .sort((a, b) => a - b);
      addSessionBands(chart, times, sessions ?? []);
    }
    series.forEach((s, i) => {
      const line = chart.addSeries(LineSeries, {
        color: SERIES_COLORS[i % SERIES_COLORS.length],
        lineWidth: 2,
        title: s.asset,
        priceFormat: { type: 'custom', formatter: (v: number) => `${v.toFixed(2)}%` },
      });
      line.setData(s.points as never);
    });
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [series, sessions]);

  return <div ref={ref} style={{ width: '100%' }} />;
}
