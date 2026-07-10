import { useEffect, useRef } from 'react';
import { ColorType, LineSeries, createChart } from 'lightweight-charts';
import type { ReturnsSeries } from '../api';

export const SERIES_COLORS = [
  '#4f8ff7', '#f0b429', '#26a69a', '#ef5350', '#ab47bc',
  '#9ccc65', '#f0842c', '#29b6f6', '#ec407a', '#8d6e63',
];

/** Multi-asset cumulative log-return lines (%), color-coded per asset. */
export default function ReturnsChart({ series }: { series: ReturnsSeries[] }) {
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
  }, [series]);

  return <div ref={ref} style={{ width: '100%' }} />;
}
