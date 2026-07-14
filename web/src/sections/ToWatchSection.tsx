import { useEffect, useState } from 'react';
import { api, type NewsItem, type NewsTree } from '../api';
import NewsEditOverlay from '../components/NewsEditOverlay';

const fmtTs = (iso: string) => `${iso.slice(0, 16).replace('T', ' ')} UTC`;

const ROLE_ICON: Record<string, string> = {
  primary: '★', supporting: '↳+', contradicting: '↳−',
  duplicate: '≡', update: '↻',
};

function StoryNode({ node, depth, onEdit, onClose }: {
  node: NewsTree;
  depth: number;
  onEdit: (n: NewsItem) => void;
  onClose: (id: number) => void;
}) {
  // collapsed by default at every nesting level; expanding reveals the
  // story's details AND its related stories, which behave the same way
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="story-node" style={{ marginLeft: depth * 14 }}>
      <div
        className={`watch-item clickable ${node.status === 'open' ? '' : 'story-closed'}`}
        onClick={() => setExpanded((v) => !v)}
      >
        <div className="row" style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }}>
          <span className="title">
            <span className="muted small">{expanded ? '▾' : '▸'} </span>
            {depth > 0 && (
              <span className="muted small" title={node.role}>
                {ROLE_ICON[node.role] ?? '·'}{' '}
              </span>
            )}
            {node.title}
          </span>
          <span className="row" style={{ flexWrap: 'nowrap' }}>
            {depth === 0 && (
              <button className="ghost small" onClick={(e) => { e.stopPropagation(); onEdit(node); }}>
                Edit
              </button>
            )}
            {node.status === 'open' && (
              <button className="ghost small" onClick={(e) => { e.stopPropagation(); onClose(node.id); }}>
                Done ✓
              </button>
            )}
          </span>
        </div>
        <div>
          {node.effects.map((e) => <span key={e.id} className="chip effect">{e.ticker}</span>)}
          {node.tags.map((t) => <span key={t.id} className="chip tag">{t.name}</span>)}
          {depth > 0 && <span className="chip">{node.role}</span>}
          {!expanded && node.children.length > 0 && (
            <span className="chip">+{node.children.length} related</span>
          )}
        </div>
        {expanded && (
          <div className="watch-detail small">
            {node.body
              ? <p style={{ whiteSpace: 'pre-wrap' }}>{node.body}</p>
              : <p className="muted">No details recorded.</p>}
            <p className="muted">
              {node.source && <>{node.source.name} · </>}
              published {fmtTs(node.publish_time)} · {node.status}
            </p>
          </div>
        )}
      </div>
      {expanded && node.children.map((child) => (
        <StoryNode key={child.id} node={child} depth={depth + 1}
          onEdit={onEdit} onClose={onClose} />
      ))}
    </div>
  );
}

/** Open stories with their related follow-ups nested underneath. */
export default function ToWatchSection({ refreshKey }: { refreshKey: number }) {
  const [threads, setThreads] = useState<NewsTree[]>([]);
  const [editing, setEditing] = useState<NewsItem | null>(null);
  const [bump, setBump] = useState(0);

  useEffect(() => {
    api.get<NewsTree[]>('/api/news/watch').then(setThreads).catch(() => {});
  }, [refreshKey, bump]);

  const closeStory = async (id: number) => {
    await api.patch(`/api/news/${id}`, { status: 'close' });
    setBump((b) => b + 1);
  };

  return (
    <div className="card">
      <h2>To watch — open stories</h2>
      {threads.length === 0 && <p className="muted small">Nothing on the watch list.</p>}
      {threads.map((t) => (
        <StoryNode key={t.id} node={t} depth={0}
          onEdit={setEditing} onClose={closeStory} />
      ))}
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
