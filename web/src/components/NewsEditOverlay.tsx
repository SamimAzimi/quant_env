import { useEffect, useState } from 'react';
import {
  api, type AssetCategory, type NewsItem, type NewsRole, type NewsThread,
  type Source, type Tag,
} from '../api';
import MultiSelect, { type Option } from './MultiSelect';
import NewsSearchPicker from './NewsSearchPicker';
import UtcDateTimeInput from './tabs/UtcDateTimeInput';

const ROLES: NewsRole[] = ['primary', 'supporting', 'contradicting', 'duplicate', 'update'];

interface Props {
  news: NewsItem;
  onClose: () => void;
  onSaved: () => void;
}

/** Full story editor: fields, tags/effects, and parent relationships. */
export default function NewsEditOverlay({ news, onClose, onSaved }: Props) {
  const [title, setTitle] = useState(news.title);
  const [body, setBody] = useState(news.body);
  const [role, setRole] = useState<NewsRole>(news.role);
  const [statusVal, setStatusVal] = useState(news.status);
  const [publishTime, setPublishTime] = useState(`${news.publish_time}Z`);
  const [sources, setSources] = useState<Source[]>([]);
  const [sourceId, setSourceId] = useState(news.source ? String(news.source.id) : '');
  const [tags, setTags] = useState<Tag[]>([]);
  const [categories, setCategories] = useState<AssetCategory[]>([]);
  const [tagIds, setTagIds] = useState<number[]>(news.tags.map((t) => t.id));
  const [effectIds, setEffectIds] = useState<number[]>(news.effects.map((e) => e.id));
  const [parents, setParents] = useState<NewsItem[]>([]);
  const [msg, setMsg] = useState('');

  useEffect(() => {
    api.get<Tag[]>('/api/tags').then(setTags).catch(() => {});
    api.get<AssetCategory[]>('/api/effects').then(setCategories).catch(() => {});
    api.get<Source[]>('/api/sources').then(setSources).catch(() => {});
    api.get<NewsThread>(`/api/news/${news.id}/thread`)
      .then((t) => setParents(
        t.ancestors.filter((a) => t.parent_ids.includes(a.id))))
      .catch(() => {});
  }, [news.id]);

  const tagOptions: Option[] = tags.map((t) => ({ id: t.id, label: t.name }));
  const effectOptions: Option[] = categories.flatMap((c) =>
    c.assets.map((a) => ({ id: a.id, label: a.ticker, group: c.name })),
  );

  const save = async () => {
    setMsg('');
    try {
      await api.patch(`/api/news/${news.id}`, {
        title, body, role,
        status: statusVal,
        publish_time: publishTime || null,
        source_id: sourceId === '' ? null : Number(sourceId),
        tag_ids: tagIds,
        effect_ids: effectIds,
        parent_ids: parents.map((p) => p.id),
      });
      onSaved();
      onClose();
    } catch (e) {
      setMsg(String(e));
    }
  };

  return (
    <div className="overlay-backdrop" onClick={onClose}>
      <div className="overlay" onClick={(e) => e.stopPropagation()}>
        <div className="overlay-head">
          <h2>Edit story #{news.id}</h2>
          <button className="overlay-close" onClick={onClose}>×</button>
        </div>
        <div className="overlay-body">
          <label className="field">
            <span>Title</span>
            <input value={title} onChange={(e) => setTitle(e.target.value)} />
          </label>
          <label className="field">
            <span>Details</span>
            <textarea rows={3} value={body} onChange={(e) => setBody(e.target.value)} />
          </label>
          <div className="row">
            <label className="field" style={{ flex: 1 }}>
              <span>Role</span>
              <select value={role} onChange={(e) => setRole(e.target.value as NewsRole)}>
                {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
              </select>
            </label>
            <label className="field" style={{ flex: 1 }}>
              <span>Status</span>
              <select value={statusVal} onChange={(e) => setStatusVal(e.target.value as 'open' | 'close')}>
                <option value="open">open (watching)</option>
                <option value="close">close</option>
              </select>
            </label>
            <label className="field" style={{ flex: 1 }}>
              <span>Source</span>
              <select value={sourceId} onChange={(e) => setSourceId(e.target.value)}>
                <option value="">—</option>
                {sources.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </label>
          </div>
          <UtcDateTimeInput label="Publish Time (UTC)" value={publishTime} onChange={setPublishTime} />
          <span className="small muted">Tags</span>
          <MultiSelect placeholder="Tags…" options={tagOptions}
            selected={tagIds} onChange={setTagIds} />
          <span className="small muted">Effects</span>
          <MultiSelect placeholder="Effects…" options={effectOptions}
            selected={effectIds} onChange={setEffectIds} />
          <NewsSearchPicker
            label="Related to (parent stories)"
            selected={parents}
            onChange={setParents}
            excludeId={news.id}
          />
          <button className="primary" onClick={save}>Save story</button>
          {msg && <p className="error">{msg}</p>}
        </div>
      </div>
    </div>
  );
}
