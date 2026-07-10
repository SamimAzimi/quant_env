import { useEffect, useState } from 'react';
import {
  api, type AssetCategory, type NewsItem, type NewsRole, type Source, type Tag,
} from '../../api';
import MultiSelect, { type Option } from '../MultiSelect';
import NewsSearchPicker from '../NewsSearchPicker';
import UtcDateTimeInput from './UtcDateTimeInput';

const ROLES: NewsRole[] = ['primary', 'supporting', 'contradicting', 'duplicate', 'update'];

export default function NewsTab({ onSaved }: { onSaved: () => void }) {
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [role, setRole] = useState<NewsRole>('primary');
  const [sources, setSources] = useState<Source[]>([]);
  const [sourceId, setSourceId] = useState('');
  const [addingSource, setAddingSource] = useState(false);
  const [newSource, setNewSource] = useState('');
  const [publishTime, setPublishTime] = useState('');
  const [tags, setTags] = useState<Tag[]>([]);
  const [categories, setCategories] = useState<AssetCategory[]>([]);
  const [tagIds, setTagIds] = useState<number[]>([]);
  const [effectIds, setEffectIds] = useState<number[]>([]);
  const [keepOpen, setKeepOpen] = useState(false);
  const [related, setRelated] = useState<NewsItem[]>([]);
  const [status, setStatus] = useState('');

  const loadMeta = async () => {
    const [t, c, s] = await Promise.all([
      api.get<Tag[]>('/api/tags'),
      api.get<AssetCategory[]>('/api/effects'),
      api.get<Source[]>('/api/sources'),
    ]);
    setTags(t);
    setCategories(c);
    setSources(s);
  };
  useEffect(() => { loadMeta().catch((e) => setStatus(String(e))); }, []);

  const tagOptions: Option[] = tags.map((t) => ({ id: t.id, label: t.name }));
  const effectOptions: Option[] = categories.flatMap((c) =>
    c.assets.map((a) => ({
      id: a.id,
      label: a.ticker,
      group: `${c.kind === 'hard' ? 'Hard' : 'Soft'} · ${c.name}`,
    })),
  );

  const addTag = async (name: string) => {
    const tag = await api.post<Tag>('/api/tags', { name });
    await loadMeta();
    setTagIds((ids) => (ids.includes(tag.id) ? ids : [...ids, tag.id]));
  };

  const addEffect = async (name: string) => {
    let categoryId = categories.find((c) => c.kind === 'soft')?.id ?? categories[0]?.id;
    let ticker = name;
    const m = name.match(/^([\w ]+):\s*(.+)$/);
    if (m) {
      const cat = categories.find((c) => c.name.toLowerCase() === m[1].trim().toLowerCase());
      if (cat) { categoryId = cat.id; ticker = m[2]; }
    }
    if (!categoryId) return;
    const asset = await api.post<{ id: number }>('/api/effects',
      { ticker, name: ticker, category_id: categoryId });
    await loadMeta();
    setEffectIds((ids) => (ids.includes(asset.id) ? ids : [...ids, asset.id]));
  };

  const addSource = async () => {
    const n = newSource.trim();
    if (!n) return;
    const created = await api.post<Source>('/api/sources', { name: n });
    await loadMeta();
    setSourceId(String(created.id));
    setNewSource('');
    setAddingSource(false);
  };

  const save = async () => {
    setStatus('');
    try {
      await api.post('/api/news', {
        title, body, role,
        source_id: sourceId === '' ? null : Number(sourceId),
        status: keepOpen ? 'open' : 'close',
        publish_time: publishTime || null,
        tag_ids: tagIds,
        effect_ids: effectIds,
        parent_ids: related.map((r) => r.id),
      });
      setTitle(''); setBody(''); setRole('primary'); setSourceId('');
      setPublishTime(''); setTagIds([]); setEffectIds([]); setKeepOpen(false);
      setRelated([]);
      setStatus('Saved ✓');
      onSaved();
    } catch (e) {
      setStatus(String(e));
    }
  };

  return (
    <div>
      <label className="field">
        <span>News Title</span>
        <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Headline" />
      </label>
      <label className="field">
        <span>News</span>
        <textarea rows={4} value={body} onChange={(e) => setBody(e.target.value)} placeholder="Details…" />
      </label>
      <div className="row">
        <label className="field" style={{ flex: 1 }}>
          <span>Role</span>
          <select value={role} onChange={(e) => setRole(e.target.value as NewsRole)}>
            {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </label>
        <label className="field" style={{ flex: 1 }}>
          <span>Source</span>
          <div className="row" style={{ flexWrap: 'nowrap' }}>
            <select style={{ flex: 1 }} value={sourceId} onChange={(e) => setSourceId(e.target.value)}>
              <option value="">— optional —</option>
              {sources.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
            <button className="ghost" onClick={() => setAddingSource((v) => !v)}>+</button>
          </div>
        </label>
      </div>
      {addingSource && (
        <div className="row" style={{ marginBottom: 10, flexWrap: 'nowrap' }}>
          <input
            style={{ flex: 1 }}
            value={newSource}
            placeholder="New source name"
            onChange={(e) => setNewSource(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && addSource()}
          />
          <button className="primary" disabled={!newSource.trim()} onClick={addSource}>Add</button>
        </div>
      )}
      <UtcDateTimeInput
        label="Publish Time (UTC) — leave empty for now"
        value={publishTime}
        onChange={setPublishTime}
      />
      <span className="small muted">Tags</span>
      <MultiSelect
        placeholder="Select tags…"
        options={tagOptions}
        selected={tagIds}
        onChange={setTagIds}
        onAddNew={addTag}
        addPlaceholder="New tag name"
      />
      <span className="small muted">Effect (assets impacted)</span>
      <MultiSelect
        placeholder="Select affected assets…"
        options={effectOptions}
        selected={effectIds}
        onChange={setEffectIds}
        onAddNew={addEffect}
        addPlaceholder="New ticker (or 'Crypto: DOGEUSDT')"
      />
      <NewsSearchPicker
        label="Related stories (this news will link under them)"
        selected={related}
        onChange={setRelated}
      />
      <label className="row" style={{ margin: '10px 0' }}>
        <input type="checkbox" checked={keepOpen} onChange={(e) => setKeepOpen(e.target.checked)} />
        Keep open — stays in To Watch until closed
      </label>
      <button className="primary" disabled={!title.trim()} onClick={save}>Save news</button>
      {status && <p className={status.startsWith('Saved') ? 'small' : 'error'}>{status}</p>}
    </div>
  );
}
