import { useEffect, useRef } from 'react';
import {
  CandlestickSeries, ColorType, LineStyle, createChart,
} from 'lightweight-charts';
import type { AssetChart } from '../api';

const LEVEL_COLORS: Record<string, string> = {
  preday: '#f0b429',
  'session:sydney': '#ab47bc',
  'session:tokyo': '#ef5350',
  'session:london': '#4f8ff7',
  'session:newyork': '#26a69a',
};

/** Candlestick chart of yesterday's bars with key-level price lines. */
export default function CandleChart({ data }: { data: AssetChart }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;
    const chart = createChart(ref.current, {
      height: 260,
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
    const series = chart.addSeries(CandlestickSeries, {
      upColor: '#26a69a', downColor: '#ef5350',
      wickUpColor: '#26a69a', wickDownColor: '#ef5350',
      borderVisible: false,
    });
    series.setData(data.bars as never);

    for (const level of data.levels) {
      series.createPriceLine({
        price: level.value,
        color: LEVEL_COLORS[level.kind] ?? '#8b93a3',
        lineWidth: 1,
        lineStyle: level.kind === 'preday' ? LineStyle.Solid : LineStyle.Dashed,
        axisLabelVisible: true,
        title: level.label,
      });
    }
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [data]);

  return <div ref={ref} style={{ width: '100%' }} />;
}
