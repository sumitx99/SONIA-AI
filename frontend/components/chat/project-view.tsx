"use client";

import { useEffect, useRef, useState, type ChangeEvent, type ReactNode } from "react";
import * as AlertDialog from "@radix-ui/react-alert-dialog";
import { Check, FileText, Folder, Loader2, MessageSquare, Pencil, Plus, Trash2, X } from "lucide-react";
import { MemoryPanel } from "@/components/account/memory-panel";
import deleteStyles from "@/components/chat/delete-confirmation.module.css";
import styles from "@/components/chat/projects.module.css";
import {
  deleteProject, deleteProjectFile, handleApiError, updateProject, uploadPDF, type ChatSession, type Project,
} from "@/lib/api";

/** A project's page: its chats, instructions, files and (for project-only memory) its memory. */
export function ProjectView({ project, chats, onOpenChat, onChange, onDeleted, onFilesChanged, renderChatActions }: {
  project: Project;
  chats: ChatSession[];
  onOpenChat: (id: string) => void;
  onChange: (project: Project) => void;
  onDeleted: (id: string) => void;
  /** Reload projects after a file finished uploading (its text is then searchable). */
  onFilesChanged: () => void;
  /** Extra controls for a chat row, e.g. moving it out of the project. */
  renderChatActions?: (chat: ChatSession) => ReactNode;
}) {
  const [renaming, setRenaming] = useState(false);
  const [name, setName] = useState(project.name);
  const [instructions, setInstructions] = useState(project.instructions);
  const [busy, setBusy] = useState<string | null>(null);
  const [uploadStatus, setUploadStatus] = useState("");
  const [error, setError] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => { setName(project.name); setInstructions(project.instructions); setRenaming(false); setError(""); },
    [project.id, project.name, project.instructions]);

  async function run(action: string, work: () => Promise<void>) {
    setBusy(action); setError("");
    try { await work(); } catch (reason) { setError(handleApiError(reason)); } finally { setBusy(null); }
  }
  const saveName = () => {
    if (!name.trim() || name.trim() === project.name) { setRenaming(false); setName(project.name); return; }
    void run("rename", async () => { onChange(await updateProject(project.id, { name: name.trim() })); setRenaming(false); });
  };
  const saveInstructions = () => void run("instructions", async () => onChange(await updateProject(project.id, { instructions })));
  async function addFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".pdf")) { setError("Please choose a PDF document."); return; }
    await run("upload", async () => {
      const response = await uploadPDF(file, undefined, setUploadStatus, project.id);
      if (response.success === false) throw new Error(response.message || "The document could not be processed");
      onFilesChanged();
    });
    setUploadStatus("");
  }

  const instructionsChanged = instructions !== project.instructions;
  return <section className={styles.project} aria-labelledby="project-title">
    <header className={styles.projectHeader}>
      <span className={styles.projectIcon}><Folder size={22} aria-hidden="true" /></span>
      {renaming
        ? <div className={styles.rename}>
            <input aria-label="Project name" autoFocus value={name} maxLength={100} disabled={!!busy}
              onChange={event => setName(event.target.value)}
              onKeyDown={event => { if (event.key === "Enter") saveName(); if (event.key === "Escape") { setRenaming(false); setName(project.name); } }} />
            <button type="button" className="icon-button" aria-label="Save name" onClick={saveName} disabled={!!busy}><Check size={15} /></button>
            <button type="button" className="icon-button" aria-label="Cancel rename" onClick={() => { setRenaming(false); setName(project.name); }}><X size={15} /></button>
          </div>
        : <h1 id="project-title">{project.name}
            <button type="button" className="icon-button" aria-label="Rename project" onClick={() => setRenaming(true)}><Pencil size={14} /></button></h1>}
      <span className={styles.badge}>{project.memoryMode === "project_only" ? "Project-only memory" : "Shared memory"}</span>
    </header>
    <p className={styles.lead}>Start a chat below. Every chat here uses this project’s instructions and files.</p>

    <div className={styles.grid}>
      <section className={styles.card} aria-labelledby="project-chats">
        <h2 id="project-chats">Chats</h2>
        {chats.length ? <ul className={styles.chatList}>
          {chats.map(chat => <li key={chat.id}><button type="button" onClick={() => onOpenChat(chat.id)}>
            <MessageSquare size={14} aria-hidden="true" /><span>{chat.title}</span></button>{renderChatActions?.(chat)}</li>)}
        </ul> : <p className={styles.muted}>No chats yet.</p>}
      </section>

      <section className={styles.card} aria-labelledby="project-instructions">
        <h2 id="project-instructions">Instructions</h2>
        <p className={styles.muted}>How Sonia should work in this project: tone, focus, what to keep in mind.</p>
        <textarea className={styles.instructions} value={instructions} maxLength={8000} rows={5} disabled={!!busy}
          placeholder="e.g. Answer as a pharmacology tutor. Keep explanations short and cite the uploaded papers."
          aria-labelledby="project-instructions" onChange={event => setInstructions(event.target.value)} />
        <div className={styles.cardActions}>
          <small className={styles.muted}>{instructions.length}/8000</small>
          <button type="button" className="account-save-button" disabled={!!busy || !instructionsChanged} onClick={saveInstructions}>
            {busy === "instructions" && <Loader2 size={14} className="animate-spin" />}Save</button>
        </div>
      </section>

      <section className={styles.card} aria-labelledby="project-files">
        <h2 id="project-files">Files</h2>
        <p className={styles.muted}>PDFs here are searched in every chat of this project.</p>
        <ul className={styles.itemList}>
          {project.documents.map(file => <li key={file.id}><span><FileText size={13} aria-hidden="true" /> {file.filename}</span>
            <button type="button" className="icon-button" aria-label={`Remove ${file.filename}`} disabled={!!busy}
              onClick={() => void run(`file-${file.id}`, async () => {
                await deleteProjectFile(project.id, file.id);
                onChange({ ...project, documents: project.documents.filter(item => item.id !== file.id) });
              })}><Trash2 size={13} /></button></li>)}
          {!project.documents.length && <li className={styles.muted}>No files yet.</li>}
        </ul>
        <button type="button" className="account-secondary-button" disabled={!!busy} onClick={() => fileInput.current?.click()}>
          {busy === "upload" ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}
          {busy === "upload" ? uploadStatus || "Uploading…" : "Add a PDF"}</button>
        <input ref={fileInput} type="file" accept=".pdf,application/pdf" className="sr-only" tabIndex={-1}
          aria-label="Upload a PDF to this project" onChange={addFile} />
      </section>

      {project.memoryMode === "project_only" && <section className={styles.card} aria-labelledby="project-memory">
        <h2 id="project-memory">Project memory</h2>
        <MemoryPanel projectId={project.id} />
      </section>}
    </div>

    {error && <p role="alert" className="form-notice">{error}</p>}
    <button type="button" className={styles.dangerLink} disabled={!!busy} onClick={() => setConfirmDelete(true)}>Delete project…</button>

    <AlertDialog.Root open={confirmDelete} onOpenChange={open => { if (!busy) setConfirmDelete(open); }}>
      <AlertDialog.Portal>
        <AlertDialog.Overlay className={deleteStyles.overlay} />
        <AlertDialog.Content className={deleteStyles.dialog}>
          <span className={deleteStyles.icon}><Trash2 size={21} /></span>
          <AlertDialog.Title className={deleteStyles.title}>Delete this project?</AlertDialog.Title>
          <AlertDialog.Description className={deleteStyles.description}>
            “{project.name}”, its {chats.length} chat{chats.length === 1 ? "" : "s"}, files{project.memoryMode === "project_only" ? " and memory" : ""} will be removed. You can’t undo this action.
          </AlertDialog.Description>
          {error && <p className={deleteStyles.error} role="alert">{error}</p>}
          <div className={deleteStyles.actions}>
            <AlertDialog.Cancel className={deleteStyles.cancel} disabled={!!busy}>Cancel</AlertDialog.Cancel>
            <button type="button" className={deleteStyles.confirm} disabled={!!busy}
              onClick={() => void run("delete", async () => { await deleteProject(project.id); setConfirmDelete(false); onDeleted(project.id); })}>
              {busy === "delete" ? "Deleting…" : "Delete project"}</button>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  </section>;
}
