import { HistogramSeries, type IChartApi } from 'lightweight-charts';
import type { SessionSpan } from '../api';

// Translucent background color per session (key from the API).
export const SESSION_COLORS: Record<string, string> = {
  sydney: 'rgba(171, 71, 188, 0.14)',
  tokyo: 'rgba(239, 83, 80, 0.12)',
  london: 'rgba(79, 143, 247, 0.12)',
  newyork: 'rgba(38, 166, 154, 0.14)',
};

// Solid variants for legends.
export const SESSION_LEGEND: Record<string, string> = {
  sydney: '#ab47bc',
  tokyo: '#ef5350',
  london: '#4f8ff7',
  newyork: '#26a69a',
};

/**
 * Shade session spans as full-height background bands.
 *
 * One histogram series per session on a hidden overlay price scale with
 * zero margins: every bar inside a span gets value 1, so the columns fill
 * the pane top-to-bottom and read as a background. Overlapping sessions
 * blend because the colors are translucent.
 */
export function addSessionBands(
  chart: IChartApi,
  times: number[],
  spans: SessionSpan[],
): void {
  const byKey = new Map<string, SessionSpan[]>();
  for (const span of spans) {
    byKey.set(span.key, [...(byKey.get(span.key) ?? []), span]);
  }
  for (const [key, keySpans] of byKey) {
    const inSpan = times.filter((t) =>
      keySpans.some((s) => t >= s.start && t < s.end));
    if (inSpan.length === 0) continue;
    const series = chart.addSeries(HistogramSeries, {
      color: SESSION_COLORS[key] ?? 'rgba(139, 147, 163, 0.10)',
      priceScaleId: `session-${key}`,
      base: 0,
      lastValueVisible: false,
      priceLineVisible: false,
    });
    series.setData(inSpan.map((time) => ({ time: time as never, value: 1 })));
    chart.priceScale(`session-${key}`).applyOptions({
      scaleMargins: { top: 0, bottom: 0 },
      visible: false,
    });
  }
}
