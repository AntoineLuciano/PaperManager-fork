// Modelled on the thesis desk's SessionList: newest first, forks nested under their chat.
import { useState, type ReactNode } from "react";
import type { Conversation } from "../../types";
import { laneColour } from "./BranchLane";

function fmtDate(iso: string) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const sameDay = d.toDateString() === new Date().toDateString();
  return sameDay ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : d.toLocaleDateString([], { day: "2-digit", month: "short" });
}

/** The conversations to show for a search: matches, plus the parents that keep a matching fork in place. */
export function filterConversations(convs: Conversation[], query: string): Conversation[] {
  const q = query.trim().toLowerCase();
  if (!q) return convs;
  const byId = new Map(convs.map((c) => [c.id, c]));
  const keep = new Set<string>();
  for (const c of convs) {
    if (`${c.title} ${c.branch_label ?? ""}`.toLowerCase().includes(q)) {
      for (let x: Conversation | undefined = c; x && !keep.has(x.id); x = x.parent_id ? byId.get(x.parent_id) : undefined) keep.add(x.id);
    }
  }
  return convs.filter((c) => keep.has(c.id));
}

type Props = {
  conversations: Conversation[];
  current: string | null;
  onPick: (c: Conversation) => void;
  onNew: () => void;
  onRename: (c: Conversation, title: string) => void;
  onDelete: (c: Conversation) => void;
};

export function ConversationList({ conversations, current, onPick, onNew, onRename, onDelete }: Props) {
  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [confirm, setConfirm] = useState<string | null>(null);

  const shown = filterConversations(conversations, query);
  const ids = new Set(shown.map((c) => c.id));
  const kids = new Map<string, Conversation[]>();
  const roots: Conversation[] = [];
  for (const c of shown) {
    if (c.parent_id && ids.has(c.parent_id)) kids.set(c.parent_id, [...(kids.get(c.parent_id) ?? []), c]);
    else roots.push(c);
  }

  const startRename = (c: Conversation) => { setEditing(c.id); setDraft(c.title); setConfirm(null); };
  const commit = (c: Conversation) => {
    const t = draft.trim();
    if (t && t !== c.title) onRename(c, t);
    setEditing(null);
  };

  const row = (c: Conversation): ReactNode => {
    const fork = c.parent_id ? { kind: (c.fork_kind ?? "strand") as "strand" | "edit" } : null;
    const children = (kids.get(c.id) ?? []).sort((a, b) => (a.fork_at ?? 0) - (b.fork_at ?? 0) || a.created_at.localeCompare(b.created_at));
    return (
      <div key={c.id}>
        <div className={`kc-row ${c.id === current ? "current" : ""} ${fork ? "branch" : ""}`}
          style={{ ["--c" as string]: laneColour(fork) }}
          onClick={() => editing !== c.id && onPick(c)}>
          {editing === c.id ? (
            <input className="kc-rename" value={draft} autoFocus aria-label="Conversation title"
              onChange={(e) => setDraft(e.target.value)} onBlur={() => commit(c)}
              onKeyDown={(e) => { if (e.key === "Enter") commit(c); if (e.key === "Escape") setEditing(null); }} />
          ) : (
            <div className="kc-row-title">
              {fork && <span className="kc-branch-glyph">⑂</span>}
              <span>{fork ? c.branch_label || "(nothing asked yet)" : c.title}</span>
            </div>
          )}
          <div className="kc-row-meta">
            {fork ? `${fork.kind} · after ${c.fork_at ?? 0} · ` : ""}{fmtDate(c.updated_at)}
            {c.message_count > 0 && ` · ${Math.ceil(c.message_count / 2)} q`}
            {c.compacted && " · compacted"}
          </div>
          <span className="kc-row-tools" onClick={(e) => e.stopPropagation()}>
            {confirm === c.id ? (
              <>
                <button type="button" className="kc-mini danger" onClick={() => { onDelete(c); setConfirm(null); }}>delete</button>
                <button type="button" className="kc-mini" onClick={() => setConfirm(null)}>keep</button>
              </>
            ) : (
              <>
                <button type="button" className="kc-mini" title="Rename" onClick={() => startRename(c)}>rename</button>
                <button type="button" className="kc-mini" title="Delete this conversation" onClick={() => setConfirm(c.id)}>×</button>
              </>
            )}
          </span>
        </div>
        {children.length > 0 && <div className="kc-kids">{children.map(row)}</div>}
      </div>
    );
  };

  return (
    <div className="kc-sessions">
      <div className="kc-sessions-head">
        <span className="kc-kicker">Conversations</span>
        <button type="button" className="kc-mini primary" onClick={onNew}>+ New</button>
      </div>
      <div className="kc-search">
        <input type="search" placeholder="Search conversations" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search conversations" />
      </div>
      <div className="kc-sessions-body">
        {roots.map(row)}
        {!roots.length && <div className="kc-empty">{conversations.length ? "No conversation matches." : "No conversations yet."}</div>}
      </div>
    </div>
  );
}
