"use client";

import { useState, type FormEvent } from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { Folder, Lightbulb, Loader2, X } from "lucide-react";
import { createProject, handleApiError, type MemoryMode, type Project } from "@/lib/api";
import styles from "@/components/chat/projects.module.css";

const modes: { id: MemoryMode; title: string; description: string }[] = [
  { id: "default", title: "Shared memory",
    description: "Chats in this project can use what Sonia remembers from your other chats, and the other way round." },
  { id: "project_only", title: "Project-only memory",
    description: "This project keeps its own memory. Its chats and your other chats never see each other. You can’t change this later." },
];

export function ProjectDialog({ open, onOpenChange, onCreated }: {
  open: boolean; onOpenChange: (open: boolean) => void; onCreated: (project: Project) => void;
}) {
  const [name, setName] = useState("");
  const [mode, setMode] = useState<MemoryMode>("default");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  function close(next: boolean) {
    if (busy) return;
    if (!next) { setName(""); setMode("default"); setError(""); }
    onOpenChange(next);
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!name.trim() || busy) return;
    setBusy(true); setError("");
    try {
      onCreated(await createProject(name.trim(), mode));
      setBusy(false);
      setName(""); setMode("default");
      onOpenChange(false);
    } catch (reason) {
      setError(handleApiError(reason));
      setBusy(false);
    }
  }

  return <DialogPrimitive.Root open={open} onOpenChange={close}>
    <DialogPrimitive.Portal>
    <DialogPrimitive.Overlay className="account-dialog-overlay" />
    <DialogPrimitive.Content className={`account-dialog-content ${styles.dialog}`}>
      <DialogPrimitive.Title className={styles.dialogTitle}>New project</DialogPrimitive.Title>
      <DialogPrimitive.Description className={styles.dialogLead}>Name it and choose how its memory works.</DialogPrimitive.Description>
      <DialogPrimitive.Close className={styles.close} aria-label="Close" disabled={busy}><X size={18} /></DialogPrimitive.Close>
      <form onSubmit={submit}>
        <label className={styles.label} htmlFor="project-name">Project name</label>
        <span className={styles.nameField}><Folder size={16} aria-hidden="true" />
          <input id="project-name" autoFocus value={name} maxLength={100} placeholder="e.g. Thesis research" disabled={busy}
            onChange={event => setName(event.target.value)} /></span>
        <p className={styles.tip}><Lightbulb size={16} aria-hidden="true" />
          Projects keep chats, files and instructions together. Use them for ongoing work, or just to stay organised.</p>
        <fieldset className={styles.modes} disabled={busy}>
          <legend>Memory</legend>
          {modes.map(item => <label key={item.id} className={styles.mode} data-selected={mode === item.id}>
            <input type="radio" name="memory-mode" value={item.id} checked={mode === item.id} onChange={() => setMode(item.id)} />
            <span><strong>{item.title}</strong><small>{item.description}</small></span>
          </label>)}
        </fieldset>
        {error && <p role="alert" className={styles.dialogError}>{error}</p>}
        <div className={styles.dialogActions}>
          <button type="button" className={styles.secondary} disabled={busy} onClick={() => close(false)}>Cancel</button>
          <button type="submit" className={styles.primary} disabled={busy || !name.trim()}>
            {busy && <Loader2 size={14} className="animate-spin" />}Create project</button>
        </div>
      </form>
    </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  </DialogPrimitive.Root>;
}
