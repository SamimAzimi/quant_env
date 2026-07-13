import { useEffect, useState } from 'react';
import {
  api, withParams, type NewsItem, type RateSnapshot, type Reading,
} from '../api';
import Gauge from '../components/Gauge';
import RateProbChart from '../components/RateProbChart';
import ChartsSection from '../sections/ChartsSection';
import MacroSection from '../sections/MacroSection';
import PreDayStats from '../sections/PreDayStats';
import ToWatchSection from '../sections/ToWatchSection';
import TradesSection from '../sections/TradesSection';

interface StatsMeta {
  available: string[];
  default_charts: string[];
  timeframes: string[];
}

const fmtTs = (iso: string) => `${iso.slice(0, 16).replace('T', ' ')} UTC`;
const todayIso = () => new Date().toISOString().slice(0, 10);
const tomorrowIso = () => {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() + 1);
  return d.toISOString().slice(0, 10);
};

export default function MarketPrepPage({ refreshKey }: { refreshKey: number }) {
  // '' means live "today"; any other value replays that day.
  const [viewDate, setViewDate] = useState('');
  const dateParam = viewDate && viewDate !== todayIso() ? viewDate : '';

  const [meta, setMeta] = useState<StatsMeta>({
    available: [], default_charts: [], timeframes: ['15m'],
  });
  const [fearGreed, setFearGreed] = useState<Reading | null>(null);
  const [vix, setVix] = useState<Reading | null>(null);
  const [rateToday, setRateToday] = useState<RateSnapshot | null>(null);
  const [ratePrev, setRatePrev] = useState<RateSnapshot | null>(null);
  const [todayNews, setTodayNews] = useState<NewsItem[]>([]);
  const [yesterdayNews, setYesterdayNews] = useState<NewsItem[]>([]);

  useEffect(() => {
    api.get<StatsMeta>('/api/stats/assets').then(setMeta).catch(() => {});
  }, []);

  useEffect(() => {
    const p = { date: dateParam };
    api.get<Reading[]>(withParams('/api/fear-greed/previous-day', p))
      .then((r) => setFearGreed(r[0] ?? null)).catch(() => {});
    api.get<Reading[]>(withParams('/api/vix/previous-day', p))
      .then((r) => setVix(r[0] ?? null)).catch(() => {});
    api.get<RateSnapshot | null>(withParams('/api/rate-probs/latest', p))
      .then(setRateToday).catch(() => {});
    api.get<RateSnapshot | null>(withParams('/api/rate-probs/previous-day', p))
      .then(setRatePrev).catch(() => {});
    api.get<NewsItem[]>(withParams('/api/news/today', p))
      .then(setTodayNews).catch(() => {});
    api.get<NewsItem[]>(withParams('/api/news/yesterday', p))
      .then(setYesterdayNews).catch(() => {});
  }, [refreshKey, dateParam]);

  const viewingPast = dateParam !== '';

  return (
    <main className="page">
      <div className="page-toolbar">
        <label className="row small">
          <span className="muted">Viewing date</span>
          <input
            type="date"
            max={tomorrowIso()}
            value={viewDate || todayIso()}
            onChange={(e) => setViewDate(e.target.value)}
          />
        </label>
        {viewingPast && (
          <button className="ghost small" onClick={() => setViewDate('')}>
            ← Back to today
          </button>
        )}
        <h1 className="page-title">
          Market Prep
          {viewingPast &&
            ` — ${dateParam}${dateParam === tomorrowIso() ? ' (tomorrow)' : ''}`}
        </h1>
      </div>

      {yesterdayNews.length > 0 && (
        <div className="ticker" style={{ marginBottom: 14 }}>
          <div className="ticker-inner">
            {yesterdayNews.map((n) => (
              <span key={n.id} className="item">
                📰 <strong>{n.title}</strong>
                {n.effects.map((e) => (
                  <span key={e.id} className="chip effect">{e.ticker}</span>
                ))}
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="stats-grid">
        <div className="card">
          <h2>Sentiment</h2>
          {fearGreed ? (
            <Gauge
              value={fearGreed.value}
              label="Fear & Greed"
              sublabel={`recorded ${fmtTs(fearGreed.ts)}`}
            />
          ) : (
            <p className="muted small">No Fear &amp; Greed recorded the day before.</p>
          )}
          <div style={{ marginTop: 10 }}>
            {vix ? (
              <div className="row" style={{ justifyContent: 'center' }}>
                <span className="muted">VIX</span>
                <span style={{ fontSize: 26, fontWeight: 700 }}>{vix.value.toFixed(2)}</span>
                <span className="small muted">{fmtTs(vix.ts)}</span>
              </div>
            ) : (
              <p className="muted small" style={{ textAlign: 'center' }}>
                No VIX recorded the day before.
              </p>
            )}
          </div>
        </div>

        <MacroSection refreshKey={refreshKey} date={dateParam} />

        <div className="card">
          <h2>Rate probabilities</h2>
          <RateProbChart today={rateToday} previous={ratePrev} />
        </div>

        <ToWatchSection refreshKey={refreshKey} />

        <div className="card">
          <h2>{viewingPast ? `News on ${dateParam}` : 'Today news'}</h2>
          {todayNews.length === 0 && <p className="muted small">Nothing recorded.</p>}
          {todayNews.map((n) => (
            <div key={n.id} className="news-item">
              <span className="title">{n.title}</span>{' '}
              {n.effects.map((e) => <span key={e.id} className="chip effect">{e.ticker}</span>)}
              {n.tags.map((t) => <span key={t.id} className="chip tag">{t.name}</span>)}
              {n.body && <div className="small muted">{n.body}</div>}
            </div>
          ))}
        </div>

        <TradesSection refreshKey={refreshKey} date={dateParam} />

        <PreDayStats
          timeframes={meta.timeframes}
          available={meta.available}
          defaults={meta.default_charts}
          date={dateParam}
        />

        <ChartsSection timeframes={meta.timeframes} date={dateParam} />
      </div>
    </main>
  );
}
