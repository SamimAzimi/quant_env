import { useEffect, useState } from 'react';
import {
  api, type NewsItem, type RateSnapshot, type Reading,
} from '../api';
import Gauge from '../components/Gauge';
import RateProbChart from '../components/RateProbChart';
import ChartsSection from '../sections/ChartsSection';
import MacroSection from '../sections/MacroSection';
import PreDayStats from '../sections/PreDayStats';
import TradesSection from '../sections/TradesSection';

interface StatsMeta {
  available: string[];
  default_charts: string[];
  timeframes: string[];
}

const fmtTs = (iso: string) => `${iso.slice(0, 16).replace('T', ' ')} UTC`;

export default function StatsPage({ refreshKey }: { refreshKey: number }) {
  const [meta, setMeta] = useState<StatsMeta>({
    available: [], default_charts: [], timeframes: ['15m'],
  });
  const [fearGreed, setFearGreed] = useState<Reading | null>(null);
  const [vix, setVix] = useState<Reading | null>(null);
  const [rateToday, setRateToday] = useState<RateSnapshot | null>(null);
  const [ratePrev, setRatePrev] = useState<RateSnapshot | null>(null);
  const [watch, setWatch] = useState<NewsItem[]>([]);
  const [todayNews, setTodayNews] = useState<NewsItem[]>([]);
  const [yesterdayNews, setYesterdayNews] = useState<NewsItem[]>([]);

  useEffect(() => {
    api.get<StatsMeta>('/api/stats/assets').then(setMeta).catch(() => {});
  }, []);

  useEffect(() => {
    api.get<Reading[]>('/api/fear-greed/previous-day')
      .then((r) => setFearGreed(r[0] ?? null)).catch(() => {});
    api.get<Reading[]>('/api/vix/previous-day')
      .then((r) => setVix(r[0] ?? null)).catch(() => {});
    api.get<RateSnapshot | null>('/api/rate-probs/latest')
      .then(setRateToday).catch(() => {});
    api.get<RateSnapshot | null>('/api/rate-probs/previous-day')
      .then(setRatePrev).catch(() => {});
    api.get<NewsItem[]>('/api/news/watch').then(setWatch).catch(() => {});
    api.get<NewsItem[]>('/api/news/today').then(setTodayNews).catch(() => {});
    api.get<NewsItem[]>('/api/news/yesterday').then(setYesterdayNews).catch(() => {});
  }, [refreshKey]);

  const dismissWatch = async (id: number) => {
    await api.patch(`/api/news/${id}`, { to_watch: false });
    setWatch((w) => w.filter((n) => n.id !== id));
  };

  return (
    <main className="page">
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
            <p className="muted small">No Fear &amp; Greed recorded yesterday.</p>
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
                No VIX recorded yesterday.
              </p>
            )}
          </div>
        </div>

        <MacroSection refreshKey={refreshKey} />

        <div className="card">
          <h2>Rate probabilities</h2>
          <RateProbChart today={rateToday} previous={ratePrev} />
        </div>

        <div className="card">
          <h2>To watch</h2>
          {watch.length === 0 && <p className="muted small">Nothing on the watch list.</p>}
          {watch.map((n) => (
            <div key={n.id} className="watch-item">
              <div className="row" style={{ justifyContent: 'space-between' }}>
                <span className="title">{n.title}</span>
                <button className="ghost small" onClick={() => dismissWatch(n.id)}>
                  Done ✓
                </button>
              </div>
              <div>
                {n.effects.map((e) => <span key={e.id} className="chip effect">{e.ticker}</span>)}
                {n.tags.map((t) => <span key={t.id} className="chip tag">{t.name}</span>)}
              </div>
            </div>
          ))}
        </div>

        <div className="card">
          <h2>Today news</h2>
          {todayNews.length === 0 && <p className="muted small">Nothing recorded today.</p>}
          {todayNews.map((n) => (
            <div key={n.id} className="news-item">
              <span className="title">{n.title}</span>{' '}
              {n.effects.map((e) => <span key={e.id} className="chip effect">{e.ticker}</span>)}
              {n.tags.map((t) => <span key={t.id} className="chip tag">{t.name}</span>)}
              {n.body && <div className="small muted">{n.body}</div>}
            </div>
          ))}
        </div>

        <TradesSection refreshKey={refreshKey} />

        <PreDayStats
          timeframes={meta.timeframes}
          available={meta.available}
          defaults={meta.default_charts}
        />

        <ChartsSection timeframes={meta.timeframes} />
      </div>
    </main>
  );
}
