import { useEffect, useState } from 'react';
import { api, type AssetCategory, type Tag } from '../../api';
import MultiSelect, { type Option } from '../MultiSelect';

export default function NewsTab({ onSaved }: { onSaved: () => void }) {
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [tags, setTags] = useState<Tag[]>([]);
  const [categories, setCategories] = useState<AssetCategory[]>([]);
  const [tagIds, setTagIds] = useState<number[]>([]);
  const [effectIds, setEffectIds] = useState<number[]>([]);
  const [toWatch, setToWatch] = useState(false);
  const [status, setStatus] = useState('');

  const loadMeta = async () => {
    const [t, c] = await Promise.all([
      api.get<Tag[]>('/api/tags'),
      api.get<AssetCategory[]>('/api/effects'),
    ]);
    setTags(t);
    setCategories(c);
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
    // New effects land in the first soft category unless the user prefixes
    // "Category: TICKER" (e.g. "Crypto: DOGEUSDT").
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

  const save = async () => {
    setStatus('');
    try {
      await api.post('/api/news', {
        title, body, tag_ids: tagIds, effect_ids: effectIds, to_watch: toWatch,
      });
      setTitle(''); setBody(''); setTagIds([]); setEffectIds([]); setToWatch(false);
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
      <label className="row" style={{ margin: '10px 0' }}>
        <input type="checkbox" checked={toWatch} onChange={(e) => setToWatch(e.target.checked)} />
        To watch — keep on the watch list until dismissed
      </label>
      <button className="primary" disabled={!title.trim()} onClick={save}>Save news</button>
      {status && <p className={status.startsWith('Saved') ? 'small' : 'error'}>{status}</p>}
    </div>
  );
}
