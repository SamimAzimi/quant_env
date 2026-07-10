import { useEffect, useRef, useState } from 'react';

export interface Option {
  id: number;
  label: string;
  group?: string;
}

interface Props {
  placeholder: string;
  options: Option[];
  selected: number[];
  onChange: (ids: number[]) => void;
  /** Called with the typed name when the user hits the + button. */
  onAddNew?: (name: string) => Promise<void>;
  addPlaceholder?: string;
}

/** Multi-select dropdown with an inline "+ add new" row at the bottom. */
export default function MultiSelect({
  placeholder, options, selected, onChange, onAddNew, addPlaceholder,
}: Props) {
  const [open, setOpen] = useState(false);
  const [newName, setNewName] = useState('');
  const [busy, setBusy] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, []);

  const toggle = (id: number) =>
    onChange(selected.includes(id) ? selected.filter((s) => s !== id) : [...selected, id]);

  const addNew = async () => {
    const name = newName.trim();
    if (!name || !onAddNew) return;
    setBusy(true);
    try {
      await onAddNew(name);
      setNewName('');
    } finally {
      setBusy(false);
    }
  };

  const groups = new Map<string, Option[]>();
  for (const opt of options) {
    const g = opt.group ?? '';
    if (!groups.has(g)) groups.set(g, []);
    groups.get(g)!.push(opt);
  }
  const byId = new Map(options.map((o) => [o.id, o]));

  return (
    <div className="mselect" ref={ref}>
      <div className="control" onClick={() => setOpen((o) => !o)}>
        {selected.length === 0 && <span className="muted">{placeholder}</span>}
        {selected.map((id) => (
          <span key={id} className="chip">{byId.get(id)?.label ?? id}</span>
        ))}
      </div>
      {open && (
        <div className="menu">
          {[...groups.entries()].map(([group, opts]) => (
            <div key={group || '_'}>
              {group && <div className="group">{group}</div>}
              {opts.map((opt) => (
                <div key={opt.id} className="opt" onClick={() => toggle(opt.id)}>
                  <input type="checkbox" readOnly checked={selected.includes(opt.id)} />
                  {opt.label}
                </div>
              ))}
            </div>
          ))}
          {onAddNew && (
            <div className="addnew">
              <input
                value={newName}
                placeholder={addPlaceholder ?? 'Add new…'}
                onChange={(e) => setNewName(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && addNew()}
              />
              <button className="primary" disabled={busy || !newName.trim()} onClick={addNew}>
                +
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
