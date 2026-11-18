"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { ArrowUp, ChevronRight, Loader2, RefreshCw, Trash2 } from "lucide-react";
import {
  addMemoryItem, deleteMemoryEntry, deleteMemoryItem, handleApiError, loadMemory, refreshMemory, resetMemory,
  setMemoryEnabled, type MemoryEntry, type MemoryOverview, type MemorySection,
} from "@/lib/api";
import styles from "@/components/chat/projects.module.css";

const sections: { id: MemorySection; title: string }[] = [
  { id: "you", title: "You" },
  { id: "topics", title: "Topics" },
  { id: "areas", title: "Areas" },
  { id: "people", title: "People" },
];

const shortDate = (value: string) => new Date(value).toLocaleDateString(undefined, { month: "short", day: "numeric" });

/** One memory entry: title, one-line description and date; opens to show what Sonia keeps. */
function EntryRow({ entry, open, onToggle, onRemove, busy }: {
  entry: MemoryEntry; open: boolean; onToggle: () => void; onRemove: () => void; busy: boolean;
}) {
  return <li className={styles.entry} data-open={open}>
    <button type="button" className={styles.entryRow} aria-expanded={open} onClick={onToggle}>
      <span className={styles.entryTitle}>{entry.title}</span>
      <span className={styles.entryDescription}>{entry.description}</span>
      <span className={styles.entryDate}>Updated {shortDate(entry.updatedAt)}</span>
    </button>
    {open && <div className={styles.entryBody}>
      <p>{entry.content}</p>
      <button type="button" className={styles.entryRemove} disabled={busy} onClick={onRemove}>
        <Trash2 size={13} />Remove from memory</button>
    </div>}
  </li>;
}

/**
 * What Sonia remembers: account-wide, or (with projectId) one project-only project.
 * Sonia organises the entries from the user's own messages; the box at the bottom adds a note.
 */
export function MemoryPanel({ projectId }: { projectId?: string }) {
  const [memory, setMemory] = useState<MemoryOverview | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [openEntry, setOpenEntry] = useState<number | null>(null);
  const [openProject, setOpenProject] = useState<string | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);

  const load = useCallback(() => {
    setError("");
    loadMemory(projectId).then(setMemory).catch(reason => setError(handleApiError(reason)));
  }, [projectId]);
  useEffect(load, [load]);

  async function run(action: string, work: () => Promise<void>) {
    setBusy(action); setError(""); setNotice("");
    try { await work(); } catch (reason) { setError(handleApiError(reason)); } finally { setBusy(null); }
  }
  const remember = (event: FormEvent) => {
    event.preventDefault();
    const content = draft.trim();
    if (!content || busy) return;
    void run("add", async () => {
      const item = await addMemoryItem(content, projectId);
      setMemory(current => current && { ...current, updating: true, edits: [...current.edits, item] });
      setDraft("");
      setNotice("Saved. Sonia will fold it into your memory in a moment.");
    });
  };
  const removeEntry = (entry: MemoryEntry, scopeProject?: string) => void run(`entry-${entry.id}`, async () => {
    await deleteMemoryEntry(entry.id, scopeProject ?? projectId);
    setMemory(current => current && {
      ...current,
      entries: current.entries.filter(item => item.id !== entry.id),
      projects: current.projects.map(project => ({ ...project, entries: project.entries.filter(item => item.id !== entry.id) })),
    });
    setOpenEntry(null);
  });
  const removeItem = (id: number) => void run(`item-${id}`, async () => {
    await deleteMemoryItem(id, projectId);
    setMemory(current => current && { ...current, edits: current.edits.filter(edit => edit.id !== id) });
  });

  if (!memory) return error
    ? <div role="alert" className="account-settings-error">{error}<button type="button" onClick={load}>Retry</button></div>
    : <p className="account-settings-loading"><Loader2 size={16} className="animate-spin" />Loading memory…</p>;

  const notes = memory.edits.filter(item => item.action === "remember");
  const forgotten = memory.edits.filter(item => item.action === "forget");
  const empty = !memory.entries.length && !notes.length;
  const toggleEntry = (id: number) => setOpenEntry(current => current === id ? null : id);

  return <div className={styles.memory}>
    <div className={styles.memoryTop}>
      <div>
        <strong>{projectId ? "Project memory" : "Memory"}</strong>
        <small>{projectId
          ? "This project keeps its own memory. Nothing here is shared with your other chats."
          : memory.enabled
            ? "Sonia remembers you across chats and can search your earlier conversations."
            : "Off. Sonia won’t use or update memory, or search past chats."}</small>
      </div>
      {!projectId && <button type="button" role="switch" aria-checked={memory.enabled} aria-label="Memory"
        className={styles.switch} disabled={!!busy}
        onClick={() => { const enabled = !memory.enabled; void run("toggle", async () => { await setMemoryEnabled(enabled); setMemory({ ...memory, enabled }); }); }} />}
    </div>

    <div className={styles.memoryBody} data-disabled={!memory.enabled}>
      <div className={styles.memoryStatus}>
        <span>{memory.updating ? "Updating with your latest chats…"
          : memory.updatedAt ? `Updated ${shortDate(memory.updatedAt)}` : "Not built yet"}</span>
        <button type="button" disabled={!!busy || !memory.enabled}
          onClick={() => void run("refresh", async () => setMemory(await refreshMemory(projectId)))}>
          {busy === "refresh" ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}Update now
        </button>
      </div>

      {empty && <p className={styles.memoryEmpty}>Nothing yet. Sonia builds this from your own messages as you chat, or tell it something below.</p>}

      {sections.map(section => {
        const entries = memory.entries.filter(entry => entry.section === section.id);
        return entries.length ? <section key={section.id} className={styles.memoryGroup}>
          <h3>{section.title}</h3>
          <ul>{entries.map(entry => <EntryRow key={entry.id} entry={entry} open={openEntry === entry.id}
            busy={!!busy} onToggle={() => toggleEntry(entry.id)} onRemove={() => removeEntry(entry)} />)}</ul>
        </section> : null;
      })}

      {!!notes.length && <section className={styles.memoryGroup}>
        <h3>Your notes</h3>
        <ul>{notes.map(item => <li key={item.id} className={styles.note}>
          <span>{item.content}</span>
          <span className={styles.entryDate}>{shortDate(item.createdAt)}</span>
          <button type="button" className="icon-button" aria-label={`Remove “${item.content}”`} disabled={!!busy}
            onClick={() => removeItem(item.id)}><Trash2 size={13} /></button>
        </li>)}</ul>
      </section>}

      {!!forgotten.length && <section className={styles.memoryGroup}>
        <h3>Asked to forget</h3>
        <ul>{forgotten.map(item => <li key={item.id} className={styles.note}>
          <span>{item.content}</span>
          <span className={styles.entryDate}>{shortDate(item.createdAt)}</span>
          <button type="button" className="icon-button" aria-label={`Allow “${item.content}” again`} disabled={!!busy}
            onClick={() => removeItem(item.id)}><Trash2 size={13} /></button>
        </li>)}</ul>
      </section>}

      {!!memory.projects.length && <section className={styles.memoryGroup}>
        <h3>Projects</h3>
        <ul>{memory.projects.map(project => <li key={project.id} className={styles.entry} data-open={openProject === project.id}>
          <button type="button" className={styles.projectRow} aria-expanded={openProject === project.id}
            onClick={() => setOpenProject(current => current === project.id ? null : project.id)}>
            <ChevronRight size={14} className={styles.chevronRight} data-open={openProject === project.id} aria-hidden="true" />
            <span>{project.name}</span>
          </button>
          {openProject === project.id && <ul className={styles.projectEntries}>
            {project.entries.length ? project.entries.map(entry => <EntryRow key={entry.id} entry={entry}
              open={openEntry === entry.id} busy={!!busy} onToggle={() => toggleEntry(entry.id)}
              onRemove={() => removeEntry(entry, project.id)} />)
              : <li className={styles.memoryEmpty}>Nothing remembered in this project yet.</li>}
          </ul>}
        </li>)}</ul>
      </section>}

      <div className={styles.resetRow}>
        {confirmReset
          ? <><span>Clear everything Sonia remembers here? Your chats stay.</span>
            <button type="button" className={styles.secondary} disabled={!!busy} onClick={() => setConfirmReset(false)}>Cancel</button>
            <button type="button" className={styles.danger} disabled={!!busy}
              onClick={() => void run("reset", async () => { setMemory(await resetMemory(projectId)); setConfirmReset(false); })}>Reset memory</button></>
          : <button type="button" className={styles.dangerLink} disabled={!!busy} onClick={() => setConfirmReset(true)}>Reset memory…</button>}
      </div>
    </div>

    <div className={styles.rememberDock}>
    <form className={styles.rememberBox} onSubmit={remember}>
      <input aria-label="Tell Sonia something to remember" value={draft} maxLength={300}
        disabled={!memory.enabled || busy === "add"} placeholder="Tell Sonia something to remember, e.g. I prefer short answers"
        onChange={event => setDraft(event.target.value)} />
      <button type="submit" aria-label="Save to memory" disabled={!memory.enabled || !!busy || !draft.trim()}>
        {busy === "add" ? <Loader2 size={15} className="animate-spin" /> : <ArrowUp size={16} />}
      </button>
    </form>
    {(error || notice) && <p role={error ? "alert" : "status"} className={error ? styles.dialogError : styles.memoryNotice}>{error || notice}</p>}
    </div>
  </div>;
}
