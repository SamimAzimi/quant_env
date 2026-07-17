import { useEffect, useRef } from 'react';
import { ColorType, LineSeries, createChart } from 'lightweight-charts';
import { SERIES_COLORS } from './ReturnsChart';

export interface LineData {
  name: string;
  points: { time: number; value: number }[];
}

interface Props {
  series: LineData[];
  height?: number;
  suffix?: string;   // value suffix, e.g. '%'
}

/** Generic multi-series line chart (UTC time axis). */
export default function MultiLineChart({ series, height = 260, suffix = '' }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;
    const chart = createChart(ref.current, {
      height,
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
        title: s.name,
        priceFormat: suffix
          ? { type: 'custom', formatter: (v: number) => `${v.toFixed(1)}${suffix}` }
          : { type: 'price', precision: 2, minMove: 0.01 },
      });
      // lightweight-charts throws on unsorted/duplicate times, which would
      // blank the chart — sort + dedupe (keep last per time) defensively
      const seen = new Map<number, { time: number; value: number }>();
      for (const p of s.points) seen.set(p.time, p);
      const pts = [...seen.values()].sort((a, b) => a.time - b.time);
      line.setData(pts as never);
    });
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [series, height, suffix]);

  return <div ref={ref} style={{ width: '100%' }} />;
}
