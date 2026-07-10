import { useEffect, useRef } from 'react';
import {
  CandlestickSeries, ColorType, createChart, createSeriesMarkers,
} from 'lightweight-charts';
import type { Bar, NewsItem } from '../api';

interface Props {
  bars: Bar[];
  news: NewsItem[];   // marked on the nearest candle by publish_time
}

/** Candles with each story pinned to the candle nearest its publish time. */
export default function NewsCandleChart({ bars, news }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current || bars.length === 0) return;
    const chart = createChart(ref.current, {
      height: 320,
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
    series.setData(bars as never);

    const times = bars.map((b) => b.time);
    const nearest = (target: number) => {
      let best = times[0];
      for (const t of times) {
        if (Math.abs(t - target) < Math.abs(best - target)) best = t;
      }
      return best;
    };

    const markers = news
      .map((n) => {
        const ts = Math.floor(new Date(`${n.publish_time}Z`).getTime() / 1000);
        return {
          time: nearest(ts) as never,
          position: 'aboveBar' as const,
          color: '#f0b429',
          shape: 'arrowDown' as const,
          text: n.title.slice(0, 24),
        };
      })
      .sort((a, b) => (a.time as unknown as number) - (b.time as unknown as number));
    createSeriesMarkers(series, markers);

    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [bars, news]);

  return <div ref={ref} style={{ width: '100%' }} />;
}
