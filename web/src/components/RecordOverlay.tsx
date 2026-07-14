import { useState } from 'react';
import AlertTab from './tabs/AlertTab';
import EconTab from './tabs/EconTab';
import FearGreedTab from './tabs/FearGreedTab';
import NewsTab from './tabs/NewsTab';
import RateTab from './tabs/RateTab';
import ThoughtsTab from './tabs/ThoughtsTab';
import TradeTab from './tabs/TradeTab';
import VixTab from './tabs/VixTab';

const TABS = [
  'News',
  'Trade Journal',
  'Analyze & Thoughts',
  'VIX',
  'Fear & Greed',
  'Economic Reports',
  'FOMC',
  'Alert',
] as const;

interface Props {
  onClose: () => void;
  onSaved: () => void;
}

export default function RecordOverlay({ onClose, onSaved }: Props) {
  const [tab, setTab] = useState<(typeof TABS)[number]>('News');

  return (
    <div className="overlay-backdrop" onClick={onClose}>
      <div className="overlay" onClick={(e) => e.stopPropagation()}>
        <div className="overlay-head">
          <h2>Record</h2>
          <button className="overlay-close" aria-label="Close" onClick={onClose}>×</button>
        </div>
        <div className="tabbar">
          {TABS.map((t) => (
            <button key={t} className={t === tab ? 'active' : ''} onClick={() => setTab(t)}>
              {t}
            </button>
          ))}
        </div>
        <div className="overlay-body">
          {tab === 'News' && <NewsTab onSaved={onSaved} />}
          {tab === 'Trade Journal' && <TradeTab onSaved={onSaved} />}
          {tab === 'Analyze & Thoughts' && <ThoughtsTab onSaved={onSaved} />}
          {tab === 'VIX' && <VixTab onSaved={onSaved} />}
          {tab === 'Fear & Greed' && <FearGreedTab onSaved={onSaved} />}
          {tab === 'Economic Reports' && <EconTab onSaved={onSaved} />}
          {tab === 'FOMC' && <RateTab onSaved={onSaved} />}
          {tab === 'Alert' && <AlertTab onSaved={onSaved} />}
        </div>
      </div>
    </div>
  );
}
