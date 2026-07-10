import { useEffect, useRef, useState } from 'react';
import { api, type NewsItem } from '../api';

interface Props {
  label: string;
  selected: NewsItem[];
  onChange: (items: NewsItem[]) => void;
  excludeId?: number;   // never offer the story itself
}

/** Fuzzy title search with multi-select — used to link related stories. */
export default function NewsSearchPicker({ label, selected, onChange, excludeId }: Props) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<NewsItem[]>([]);
  const [open, setOpen] = useState(false);
  const timer = useRef<number>();

  useEffect(() => {
    window.clearTimeout(timer.current);
    if (!query.trim()) { setResults([]); return; }
    timer.current = window.setTimeout(() => {
      api.get<NewsItem[]>(`/api/news/search?q=${encodeURIComponent(query)}`)
        .then((r) => {
          setResults(r.filter((n) => n.id !== excludeId
            && !selected.some((s) => s.id === n.id)));
          setOpen(true);
        })
        .catch(() => setResults([]));
    }, 250);
    return () => window.clearTimeout(timer.current);
  }, [query, excludeId, selected]);

  const pick = (item: NewsItem) => {
    onChange([...selected, item]);
    setQuery('');
    setResults([]);
    setOpen(false);
  };

  const remove = (id: number) => onChange(selected.filter((s) => s.id !== id));

  return (
    <div className="field">
      <span className="small muted">{label}</span>
      {selected.length > 0 && (
        <div style={{ margin: '4px 0' }}>
          {selected.map((s) => (
            <span key={s.id} className="chip">
              {s.title.slice(0, 40)}{s.title.length > 40 ? '…' : ''}
              <button className="chip-x" onClick={() => remove(s.id)}>×</button>
            </span>
          ))}
        </div>
      )}
      <div className="mselect">
        <input
          style={{ width: '100%' }}
          value={query}
          placeholder="Search news titles (fuzzy)…"
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => results.length > 0 && setOpen(true)}
        />
        {open && results.length > 0 && (
          <div className="menu">
            {results.map((n) => (
              <div key={n.id} className="opt" onClick={() => pick(n)}>
                <span>
                  {n.title}
                  <span className="muted small"> · {n.publish_time.slice(0, 10)} · {n.role}</span>
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
