import { useEffect, useState } from 'react';
import {
  api, withParams,
  type AssetCategory, type Bar, type NewsGroup, type NewsItem, type NewsThread,
  type Tag,
} from '../api';
import NewsCandleChart from '../components/NewsCandleChart';
import NewsEditOverlay from '../components/NewsEditOverlay';
import NewsSearchPicker from '../components/NewsSearchPicker';
import StoryGraph from '../components/StoryGraph';

const fmt = (iso: string) => `${iso.slice(0, 16).replace('T', ' ')} UTC`;

interface Props {
  start: string;
  end: string;
  timeframes: string[];
  chartAssets: string[];
}

interface StoryActions {
  onEdit: (n: NewsItem) => void;
  onDelete: (n: NewsItem) => void;
}

function StoryButtons({ n, onEdit, onDelete }: { n: NewsItem } & StoryActions) {
  return (
    <span className="row" style={{ flexWrap: 'nowrap' }}>
      <button className="ghost small" onClick={(e) => { e.stopPropagation(); onEdit(n); }}>
        Edit
      </button>
      <button className="ghost small danger"
        onClick={(e) => { e.stopPropagation(); onDelete(n); }}>
        Delete
      </button>
    </span>
  );
}

function StoryDetail({ n, onEdit, onDelete }: { n: NewsItem } & StoryActions) {
  return (
    <div className="news-item">
      <div className="row" style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }}>
        <span>
          <span className="title">{n.title}</span>{' '}
          <span className="chip">{n.role}</span>
          {n.source && <span className="chip">{n.source.name}</span>}
          {n.effects.map((e) => <span key={e.id} className="chip effect">{e.ticker}</span>)}
          {n.tags.map((t) => <span key={t.id} className="chip tag">{t.name}</span>)}
        </span>
        <StoryButtons n={n} onEdit={onEdit} onDelete={onDelete} />
      </div>
      <div className="small muted">published {fmt(n.publish_time)}</div>
      {n.body && <div className="small">{n.body}</div>}
    </div>
  );
}

/** Range-list row: collapsed to one line, click to expand full details. */
function HistoryRow({ n, onEdit, onDelete }: { n: NewsItem } & StoryActions) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="news-item clickable" onClick={() => setExpanded((v) => !v)}>
      <div className="row" style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }}>
        <span>
          <span className="muted small">{expanded ? '▾' : '▸'} {fmt(n.publish_time)}</span>{' '}
          <span className="title">{n.title}</span>{' '}
          <span className="chip">{n.role}</span>
          {n.effects.map((e) => <span key={e.id} className="chip effect">{e.ticker}</span>)}
          {n.tags.map((t) => <span key={t.id} className="chip tag">{t.name}</span>)}
        </span>
        <StoryButtons n={n} onEdit={onEdit} onDelete={onDelete} />
      </div>
      {expanded && (
        <div className="watch-detail small">
          {n.body
            ? <p style={{ whiteSpace: 'pre-wrap' }}>{n.body}</p>
            : <p className="muted">No details recorded.</p>}
          <p className="muted">
            {n.source && <>{n.source.name} · </>}
            status {n.status} · recorded {fmt(n.created_at)}
          </p>
        </div>
      )}
    </div>
  );
}

/** History → News: search, recursive story groups, graph, and candle map. */
export default function NewsHistorySection({ start, end, timeframes, chartAssets }: Props) {
  const [tags, setTags] = useState<Tag[]>([]);
  const [categories, setCategories] = useState<AssetCategory[]>([]);
  const [tagFilter, setTagFilter] = useState('');
  const [effectFilter, setEffectFilter] = useState('');
  const [news, setNews] = useState<NewsItem[]>([]);

  const [searchPick, setSearchPick] = useState<NewsItem[]>([]);
  const [thread, setThread] = useState<NewsThread | null>(null);

  const [groups, setGroups] = useState<NewsGroup[]>([]);
  const [groupIdx, setGroupIdx] = useState<number | null>(null);
  const [showGraph, setShowGraph] = useState(false);
  const [selected, setSelected] = useState<NewsItem | null>(null);

  const [tf, setTf] = useState('15m');
  const [asset, setAsset] = useState('');
  const [bars, setBars] = useState<Bar[]>([]);
  const [barsErr, setBarsErr] = useState('');
  const [editing, setEditing] = useState<NewsItem | null>(null);
  const [bump, setBump] = useState(0);

  const deleteStory = async (n: NewsItem) => {
    if (!window.confirm(`Delete "${n.title}"? Related stories stay.`)) return;
    await api.delete(`/api/news/${n.id}`);
    setSearchPick((p) => p.filter((s) => s.id !== n.id));
    setSelected((s) => (s?.id === n.id ? null : s));
    setBump((b) => b + 1);
  };

  useEffect(() => {
    api.get<Tag[]>('/api/tags').then(setTags).catch(() => {});
    api.get<AssetCategory[]>('/api/effects').then(setCategories).catch(() => {});
  }, []);

  const loadLists = () => {
    api.get<NewsItem[]>(withParams('/api/news/history', {
      start, end, tag_id: tagFilter, effect_id: effectFilter,
    })).then(setNews).catch(() => {});
    api.get<NewsGroup[]>(withParams('/api/news/groups', { start, end }))
      .then(setGroups).catch(() => {});
  };

  // range/filter changes reset the selection; edits (bump) just reload
  useEffect(() => {
    setGroupIdx(null);
    setSelected(null);
    loadLists();
  }, [start, end, tagFilter, effectFilter]);

  useEffect(() => { if (bump > 0) loadLists(); }, [bump]);

  // selecting a search result loads its full thread
  useEffect(() => {
    const pick = searchPick[searchPick.length - 1];
    if (!pick) { setThread(null); return; }
    api.get<NewsThread>(`/api/news/${pick.id}/thread`)
      .then(setThread).catch(() => setThread(null));
  }, [searchPick, bump]);

  const group = groupIdx !== null ? groups[groupIdx] : null;

  // group + timeframe + asset → bars covering the group's stories
  useEffect(() => {
    setBars([]); setBarsErr('');
    if (!group || !asset) return;
    const times = group.news.map((n) => n.publish_time.slice(0, 10)).sort();
    api.get<{ bars: Bar[] }>(withParams('/api/stats/bars', {
      asset, tf, start: times[0], end: times[times.length - 1],
    }))
      .then((r) => setBars(r.bars))
      .catch((e) => setBarsErr(String(e)));
  }, [group, tf, asset]);

  return (
    <div className="card span-2">
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <h2>History of news</h2>
        <div className="row">
          <select value={tagFilter} onChange={(e) => setTagFilter(e.target.value)}>
            <option value="">All tags</option>
            {tags.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
          <select value={effectFilter} onChange={(e) => setEffectFilter(e.target.value)}>
            <option value="">All effects</option>
            {categories.map((c) => (
              <optgroup key={c.id} label={c.name}>
                {c.assets.map((a) => <option key={a.id} value={a.id}>{a.ticker}</option>)}
              </optgroup>
            ))}
          </select>
        </div>
      </div>

      <NewsSearchPicker
        label="Find a story (fuzzy) — select to see everything related to it"
        selected={searchPick}
        onChange={(items) => setSearchPick(items.slice(-1))}
      />
      {thread && (
        <div className="thread-box">
          {thread.ancestors.map((a) => (
            <StoryDetail key={a.id} n={a} onEdit={setEditing} onDelete={deleteStory} />
          ))}
          <StoryDetail n={thread.tree} onEdit={setEditing} onDelete={deleteStory} />
          {thread.tree.children.map((c) => (
            <StoryDetail key={c.id} n={c} onEdit={setEditing} onDelete={deleteStory} />
          ))}
        </div>
      )}

      <h3 className="small muted" style={{ textTransform: 'uppercase', letterSpacing: '0.08em' }}>
        Story groups in range
      </h3>
      {groups.length === 0 && <p className="muted small">No stories in range.</p>}
      <div className="row" style={{ marginBottom: 8 }}>
        {groups.map((g, i) => (
          <button
            key={i}
            className={`ghost small ${groupIdx === i ? 'selected-chip' : ''}`}
            onClick={() => { setGroupIdx(groupIdx === i ? null : i); setSelected(null); }}
          >
            {g.name.slice(0, 34)}{g.name.length > 34 ? '…' : ''} ({g.news.length})
          </button>
        ))}
      </div>

      {group && (
        <div>
          <div className="row" style={{ marginBottom: 8 }}>
            <button className="ghost small" onClick={() => setShowGraph((v) => !v)}>
              {showGraph ? 'Hide graph' : 'Show graph'}
            </button>
            <select value={tf} onChange={(e) => setTf(e.target.value)}>
              {timeframes.map((t) => <option key={t}>{t}</option>)}
            </select>
            <select value={asset} onChange={(e) => setAsset(e.target.value)}>
              <option value="">— map onto asset candles —</option>
              {chartAssets.map((a) => <option key={a}>{a}</option>)}
            </select>
          </div>

          {showGraph && (
            <StoryGraph group={group} onSelect={setSelected} selectedId={selected?.id} />
          )}
          {selected && <StoryDetail n={selected} onEdit={setEditing} onDelete={deleteStory} />}

          {asset && bars.length > 0 && (
            <NewsCandleChart bars={bars} news={group.news} />
          )}
          {asset && bars.length === 0 && !barsErr && (
            <p className="muted small">No {asset} bars covering this group's dates.</p>
          )}
          {barsErr && <p className="error">{barsErr}</p>}

          {!showGraph && !selected && group.news.map((n) => (
            <StoryDetail key={n.id} n={n} onEdit={setEditing} onDelete={deleteStory} />
          ))}
        </div>
      )}

      {!group && !thread && (
        <>
          {news.map((n) => (
            <HistoryRow key={n.id} n={n} onEdit={setEditing} onDelete={deleteStory} />
          ))}
        </>
      )}

      {editing && (
        <NewsEditOverlay
          news={editing}
          onClose={() => setEditing(null)}
          onSaved={() => setBump((b) => b + 1)}
        />
      )}
    </div>
  );
}
