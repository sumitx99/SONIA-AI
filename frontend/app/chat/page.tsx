"use client";

import {
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type KeyboardEvent,
} from "react";
import { useRouter } from "next/navigation";
import * as AlertDialog from "@radix-ui/react-alert-dialog";
import deleteStyles from "@/components/chat/delete-confirmation.module.css";
import { AnimatePresence, motion, MotionConfig } from "motion/react";
import {
  ArrowUp,
  ArrowUpRight,
  Check,
  FileText,
  Menu,
  MessageSquare,
  Paperclip,
  Pencil,
  Plus,
  Play,
  Trash2,
  X,
} from "lucide-react";
import { Brand, Emblem } from "@/components/brand";
import { AccountMenu } from "@/components/account/account-menu";
import { DocumentImageGallery } from "@/components/chat/document-image";
import { WebImageGallery } from "@/components/chat/web-images";
import { MarkdownMessage } from "@/components/chat/markdown-message";
import { ToolCalls, WebSources } from "@/components/chat/tool-calls";
import { streamMessage, uploadPDF, waitForDocumentImages, deleteConversation, handleApiError, type ImageAttachment,
  type ChatMessage as Message, type ToolCall } from "@/lib/api";
import { conversationHistory, editConversation } from "@/lib/chat-context";
import { supabase } from "@/lib/supabase";
import { useSession } from "@/lib/hooks/use-session";
import { useConversations } from "@/lib/hooks/use-conversations";

const suggestions = [
  "Summarize the key ideas",
  "What are the main takeaways?",
  "Explain the document in simple terms",
];

/** The bot message announcing an uploaded document, for its current image state. */
function uploadReadyMessage(filename: string,
  images: { images_status?: string | null; images_stored?: number; warnings?: string[] }) {
  const stored = images.images_stored ?? 0;
  return {
    content: `“${filename}” is ready.${images.images_status === "ready" ? ` ${stored} image${stored === 1 ? " is" : "s are"} available—ask to see an image or specify a page.` : ""} What would you like to discover?`,
    notice: images.warnings?.join(" ") || (images.images_status === "disabled"
      ? "Image extraction is unavailable until image storage is configured."
      : images.images_status === "processing" ? "Images from this PDF are still being processed; you can already ask about its text."
      : images.images_status === "failed" ? "Text is ready, but this document's images could not be processed." : null),
  };
}

export default function SoniaChatInterface() {
  const router = useRouter();
  const [preferences, setPreferences] = useState({ reduce_motion: false, compact_mode: false });
  const { session, ready } = useSession();
  const { sessions, setSessions, loaded: historyLoaded, error: historyError,
    setError: setHistoryError, retry: retryHistory } = useConversations(session?.user.id);
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [editingMessageId, setEditingMessageId] = useState<string | null>(null);
  const [editedPrompt, setEditedPrompt] = useState("");
  const [generatingId, setGeneratingId] = useState<string | null>(null);
  const [stopped, setStopped] = useState<{ id: string; query: string; hasText: boolean } | null>(null);
  const answerController = useRef<AbortController | null>(null);
  const [pending, setPending] = useState<{
    id: string;
    kind: "answer" | "upload";
  } | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; title: string } | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const [fileError, setFileError] = useState("");
  const [uploadStatus, setUploadStatus] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const end = useRef<HTMLDivElement>(null);
  const busy = useRef(false);
  const current = sessions.find((session) => session.id === currentId);
  const messages = current?.messages ?? [];
  const answeringHere = !!generatingId && generatingId === currentId;
  const resumeAvailable = !!stopped && stopped.id === currentId && !generatingId && !pending;
  const canResume = resumeAvailable && !input.trim();
  const composerAction = answeringHere ? "stop" : canResume ? "resume" : "send";
  const composerActionLabel = answeringHere ? "Stop answering" : canResume ? "Resume answer" : "Send message";
  const toolStepCount = messages[messages.length - 1]?.tool_calls?.length ?? 0;

  useEffect(() => { setCurrentId(null); setDeleteTarget(null); setStopped(null); return () => answerController.current?.abort(); }, [session?.user.id]);

  useEffect(() => {
    if (historyLoaded && !currentId && sessions.length) setCurrentId(sessions[0].id);
  }, [historyLoaded, currentId, sessions]);

  // Signed-out visitors (or an expired session) go to the sign-in page.
  useEffect(() => {
    if (ready && !session) router.replace("/auth?next=/chat");
  }, [ready, session, router]);

  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "instant", block: "end" });
  }, [messages.length, pending, toolStepCount]);

  useEffect(() => { setEditingMessageId(null); setEditedPrompt(""); }, [currentId]);

  function newChat() {
    const id = crypto.randomUUID();
    setSessions((previous) => [
      { id, title: "Untitled conversation", messages: [], documents: [], documentIds: [] },
      ...previous,
    ]);
    setCurrentId(id);
    setInput("");
    setFileError("");
    setSidebarOpen(false);
    textarea.current?.focus();
    return id;
  }

  // Upload messages whose images are still processing: check until done, including after a reload.
  const watchedImages = useRef(new Set<string>());
  useEffect(() => {
    if (!historyLoaded) return;
    for (const chat of sessions) {
      for (const pending of chat.messages) {
        const documentId = pending.images_pending_document_id;
        if (documentId == null || watchedImages.current.has(pending.id)) continue;
        watchedImages.current.add(pending.id);
        waitForDocumentImages(documentId).then((images) => setSessions((previous) => previous.map((session) => {
          if (session.id !== chat.id) return session;
          const filename = session.documents[session.documentIds.indexOf(documentId)] ?? "Your document";
          return { ...session, messages: session.messages.map((message) => message.id === pending.id
            ? { ...message, ...uploadReadyMessage(filename, images), images_pending_document_id: null } : message) };
        }))).catch(() => watchedImages.current.delete(pending.id));
      }
    }
  }, [sessions, historyLoaded, setSessions]);

  function append(id: string, message: Message) {
    setSessions((previous) =>
      previous.map((session) =>
        session.id === id
          ? { ...session, messages: [...session.messages, message] }
          : session,
      ),
    );
  }

  async function ask(replacement?: { messageId: string; content: string }, resume = false) {
    const continuation = resume && stopped?.id === currentId ? stopped : null;
    if (resume && !continuation) return;
    const query = (continuation ? continuation.hasText
      ? "Continue the interrupted answer from where it stopped. Do not repeat the existing answer or any completed tool actions. Cite sources for additional factual claims."
      : continuation.query : replacement?.content ?? input).trim();
    if (!query || busy.current || !historyLoaded) return;
    if (replacement && !messages.some(m => m.id === replacement.messageId && m.sender === "user")) return;
    busy.current = true;
    const controller = new AbortController();
    answerController.current = controller;
    setStopped(null);
    const id = currentId ?? newChat();
    const branch = replacement ? editConversation(messages, replacement.messageId, query) : null;
    const before = branch?.before ?? (continuation && !continuation.hasText
      ? messages.slice(0, messages.findLastIndex(message => message.sender === "user")) : messages);
    if (branch) {
      setSessions(previous => previous.map(chat => chat.id === id ? { ...chat, messages: branch.messages } : chat));
    } else if (!continuation) {
      append(id, { id: crypto.randomUUID(), content: query, sender: "user" });
    }
    setGeneratingId(id);
    setEditingMessageId(null);
    if (!before.length)
      setSessions((previous) =>
        previous.map((session) =>
          session.id === id
            ? {
                ...session,
                title: query.length > 36 ? `${query.slice(0, 36)}…` : query,
              }
            : session,
        ),
      );
    if (!continuation) setInput("");
    setPending({ id, kind: "answer" });
    const answerId = crypto.randomUUID();
    let meta: { images?: ImageAttachment[]; image_notice?: string | null } = {};
    let text = "";
    let started = false;
    let toolCalls: ToolCall[] = [];
    const update = (changes: Partial<Message>) =>
      setSessions((previous) => previous.map((session) => session.id === id
        ? { ...session, messages: session.messages.map((m) => (m.id === answerId ? { ...m, ...changes } : m)) }
        : session));
    try {
      // The first words or tool step replace the "thinking" indicator with the answer itself.
      const start = () => {
        if (started) return;
        started = true;
        setPending(null);
        append(id, { id: answerId, content: "", sender: "bot", streaming: true,
                     images: meta.images, notice: meta.image_notice });
      };
      const { cutOff } = await streamMessage(query, current?.documentIds ?? [], {
        onMeta: (received) => { meta = received; },
        onDelta: (piece) => {
          start();
          text += piece;
          update({ content: text });
        },
        onToolCall: (call) => {
          start();
          const index = toolCalls.findIndex((item) => item.id === call.id);
          toolCalls = index < 0 ? [...toolCalls, call]
            : toolCalls.map((item, i) => (i === index ? { ...item, ...call } : item));
          toolCalls = toolCalls.slice(-30);
          update({ tool_calls: toolCalls });
        },
        onSources: (sources) => { start(); update({ sources }); },
        onWebImages: (images) => {
          start();
          setSessions(previous => previous.map(chat => chat.id === id ? { ...chat, messages: chat.messages.map(message =>
            message.id === answerId ? { ...message, notice: images.length ? null : message.notice, web_images: [...new Map([...(message.web_images ?? []), ...images].map(image => [image.image_id, image])).values()] } : message) } : chat));
        },
        onCitations: (answer, citations) => {
          text = answer;
          update({ content: answer, citations });
        },
      }, conversationHistory(before), controller.signal);
      controller.signal.throwIfAborted();
      toolCalls = toolCalls.map(call => call.status === "running" ? { ...call, status: cutOff ? "error" as const : "done" as const } : call);
      update({
        streaming: false, tool_calls: toolCalls,
        ...(cutOff && { notice: "The answer was cut off part-way. Ask again to get the rest." }),
      });
    } catch (error) {
      if (controller.signal.aborted) {
        setStopped({ id, query: continuation?.query ?? query, hasText: !!text || !!continuation?.hasText });
        if (started) update({ streaming: false, notice: "Answer stopped. Resume to continue.",
          tool_calls: toolCalls.map(call => call.status === "running" || call.status === "awaiting_approval" ? { ...call, status: "stopped" } : call) });
      } else if (started) {
        update({ streaming: false, tool_calls: toolCalls.map(call => call.status === "running" ? { ...call, status: "error" } : call),
          ...(text ? { notice: "The answer was cut off part-way. Ask again to get the rest." }
            : { content: handleApiError(error), error: true }) });
      } else {
        append(id, {
          id: crypto.randomUUID(),
          // The server's reason is already a sentence; only a failed request suggests the network.
          content: `I couldn’t get an answer. ${handleApiError(error).replace(/([^.!?])$/, "$1.")}${
            error instanceof TypeError ? " Please check your connection and try again." : ""}`,
          sender: "bot",
          error: true,
        });
      }
    } finally {
      if (answerController.current === controller) answerController.current = null;
      busy.current = false;
      setGeneratingId(null);
      setPending(null);
    }
  }

  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || busy.current || !historyLoaded) return;
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setFileError("Please choose a PDF document.");
      return;
    }
    setFileError("");
    busy.current = true;
    const id = currentId ?? newChat();
    setPending({ id, kind: "upload" });
    try {
      const response = await uploadPDF(file, id, setUploadStatus);
      if (response.success === false)
        throw new Error(
          response.message || "The document could not be processed",
        );
      setSessions((previous) =>
        previous.map((session) =>
          session.id === id
            ? {
                ...session,
                documents: [
                  ...session.documents,
                  response.filename || file.name,
                ],
                documentIds: [...session.documentIds, response.file_id],
                title: session.messages.length ? session.title : file.name,
              }
            : session,
        ),
      );
      append(id, {
        id: crypto.randomUUID(), sender: "bot", ...uploadReadyMessage(response.filename || file.name, response),
        // The effect that watches pending images picks this up, now and after a reload.
        images_pending_document_id: response.images_status === "processing" ? response.file_id : null,
      });
    } catch (error) {
      append(id, {
        id: crypto.randomUUID(),
        content: `The document couldn’t be uploaded. ${handleApiError(error)}. Please try again.`,
        sender: "bot",
        error: true,
      });
    } finally {
      busy.current = false;
      setPending(null);
    }
  }

  async function remove(id: string) {
    if (deleting || pending?.id === id) return;
    setDeleting(true);
    setDeleteError("");
    try {
      await deleteConversation(id);
    } catch (error) {
      setDeleteError(`The conversation could not be deleted. ${handleApiError(error)}`);
      setDeleting(false);
      return;
    }
    setSessions((previous) => previous.filter((session) => session.id !== id));
    if (currentId === id) {
      setCurrentId(null);
      setInput("");
      setFileError("");
    }
    setDeleteTarget(null);
    setDeleting(false);
  }

  function saveTitle(id: string) {
    if (title.trim())
      setSessions((previous) =>
        previous.map((session) =>
          session.id === id ? { ...session, title: title.trim() } : session,
        ),
      );
    setEditingId(null);
  }

  async function signOut() {
    await supabase.auth.signOut();
    router.replace("/auth");
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (
      event.key === "Enter" &&
      !event.shiftKey &&
      !event.nativeEvent.isComposing
    ) {
      event.preventDefault();
      void ask(undefined, canResume);
    }
  }


  if (!session) {
    return (
      <main className="chat-gate" role="status">
        {ready ? "Taking you to sign in…" : "Opening your workspace…"}
      </main>
    );
  }

  return (
    <MotionConfig reducedMotion={preferences.reduce_motion ? "always" : "user"}>
      <div className="chat-app" data-reduce-motion={preferences.reduce_motion} data-compact={preferences.compact_mode}>
        {sidebarOpen && (
          <button
            className="sidebar-scrim"
            aria-label="Close navigation"
            onClick={() => setSidebarOpen(false)}
          />
        )}
        <aside
          id="chat-sidebar"
          className={`chat-sidebar ${sidebarOpen ? "is-open" : ""}`}
          aria-label="Conversations"
        >
          <div className="sidebar-brand">
            <Brand />
            <button
              className="icon-button mobile-only"
              aria-label="Close navigation"
              onClick={() => setSidebarOpen(false)}
            >
              <X size={18} />
            </button>
          </div>
          <button className="button button-ink new-chat" onClick={newChat} disabled={!historyLoaded}>
            <Plus size={16} /> New conversation
          </button>
          <div className="sidebar-section-label mono">
            YOUR CONVERSATIONS{" "}
            <span>{String(sessions.length).padStart(2, "0")}</span>
          </div>
          <div className="session-list">
            {!sessions.length && (
              <p className="sidebar-empty">
                Every good discovery
                <br />
                starts with a question.
              </p>
            )}
            {sessions.map((session) => (
              <div
                key={session.id}
                className={`session-row ${session.id === currentId ? "active" : ""}`}
              >
                {editingId === session.id ? (
                  <div className="session-edit">
                    <input
                      aria-label="Conversation title"
                      value={title}
                      onChange={(event) => setTitle(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") saveTitle(session.id);
                        if (event.key === "Escape") setEditingId(null);
                      }}
                      autoFocus
                    />
                    <button
                      className="icon-button"
                      aria-label="Save title"
                      onClick={() => saveTitle(session.id)}
                    >
                      <Check size={14} />
                    </button>
                    <button
                      className="icon-button"
                      aria-label="Cancel rename"
                      onClick={() => setEditingId(null)}
                    >
                      <X size={14} />
                    </button>
                  </div>
                ) : (
                  <>
                    <button
                      className="session-select"
                      aria-current={
                        session.id === currentId ? "page" : undefined
                      }
                      onClick={() => {
                        setCurrentId(session.id);
                        setInput("");
                        setFileError("");
                        setSidebarOpen(false);
                      }}
                    >
                      <MessageSquare size={15} />
                      <span>{session.title}</span>
                    </button>
                    <div className="session-actions">
                      <button
                        className="icon-button"
                        aria-label={`Rename ${session.title}`}
                        onClick={() => {
                          setEditingId(session.id);
                          setTitle(session.title);
                        }}
                      >
                        <Pencil size={13} />
                      </button>
                      <button
                        className="icon-button"
                        disabled={pending?.id === session.id}
                        aria-label={`Delete ${session.title}`}
                        onClick={() => { setDeleteError(""); setDeleteTarget({ id: session.id, title: session.title }); }}
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </>
                )}
              </div>
            ))}
          </div>
          <div className="sidebar-bottom">
            <div className="sidebar-sync-status" role="status" data-sync={historyError ? "pending" : !historyLoaded ? "loading" : "saved"}>
              <span aria-hidden="true" />
              {!historyLoaded ? "Loading history…" : historyError ? "Sync pending" : "History synced"}
            </div>
            {historyError && <div role="status" className="form-notice">
              <p>{historyError}</p><button type="button" className="text-link" onClick={retryHistory}>Retry sync</button>
            </div>}
            <AccountMenu key={session.user.id} userId={session.user.id}
              email={session.user.email || ""}
              initialName={session.user.user_metadata?.full_name || session.user.user_metadata?.name}
              onSignOut={signOut} onPreferences={setPreferences} />
          </div>
        </aside>
        <main className="chat-main">
          <header className="chat-header">
            <div>
              <button
                className="icon-button mobile-only"
                aria-label="Open navigation"
                aria-controls="chat-sidebar"
                aria-expanded={sidebarOpen}
                onClick={() => setSidebarOpen(true)}
              >
                <Menu size={20} />
              </button>
              <span className="room-label">Workspace</span>
              <span className="header-slash">/</span>
              <span className="header-title">
                {current?.title ?? "A fresh perspective"}
              </span>
            </div>
            <span className="mono header-edition">
              SONIA / YOUR DOCUMENT COMPANION
            </span>
          </header>
          <div className="chat-scroll">
            {current?.recovered && !messages.length && <p role="status" className="form-notice">
              Your uploaded documents were restored. Earlier message text was not saved by the previous version.
            </p>}
            {!messages.length ? (
              <motion.div
                className="chat-welcome"
                initial={{ opacity: 0, y: 15 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5 }}
              >
                <Emblem />
                <p className="eyebrow">YOUR DOCUMENTS. A NEW PERSPECTIVE.</p>
                <h1>
                  Your next insight
                  <br />
                  <em>starts here.</em>
                </h1>
                <p>
                  Bring the document. Ask the question.
                  <br />
                  Let’s find something worth knowing.
                </p>
                <button
                  className="upload-invite"
                  onClick={() => fileInput.current?.click()}
                  disabled={!!pending}
                >
                  <span className="upload-icon">
                    <FileText size={23} strokeWidth={1.2} />
                  </span>
                  <span>
                    <strong>Put a document on the desk</strong>
                    <small>Choose a PDF to get the conversation started</small>
                  </span>
                  <Plus size={20} />
                </button>
                <div className="prompt-suggestions">
                  {suggestions.map((suggestion) => (
                    <button
                      key={suggestion}
                      onClick={() => {
                        setInput(suggestion);
                        textarea.current?.focus();
                      }}
                    >
                      {suggestion}
                      <ArrowUpRight size={13} />
                    </button>
                  ))}
                </div>
              </motion.div>
            ) : (
              <div className="message-list">
                <AnimatePresence initial={false}>
                  {messages.map((message) => (
                    <motion.article
                      key={message.id}
                      className={`chat-message ${message.sender === "user" ? "from-user" : "from-sonia"} ${message.error ? "message-error" : ""}`}
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ duration: 0.25 }}
                    >
                      <div className="message-label mono">
                        {message.sender === "bot" && <Emblem />}
                        {message.sender === "bot" ? "SONIA" : "YOU"}
                        {message.sender === "user" && editingMessageId !== message.id && <button type="button" className="edit-prompt-button" aria-label="Edit prompt" title="Edit prompt" disabled={!!generatingId || !!pending} onClick={() => { setEditingMessageId(message.id); setEditedPrompt(message.content); }}><Pencil size={13} /></button>}
                      </div>
                      {message.sender === "bot" && <ToolCalls calls={message.tool_calls} streaming={message.streaming} />}
                      {message.sender === "bot" && message.streaming && <WebSources sources={message.sources} />}
                      {editingMessageId === message.id ? <form className="prompt-edit-form" onSubmit={event => { event.preventDefault(); void ask({ messageId: message.id, content: editedPrompt }); }}>
                        <label className="sr-only" htmlFor={`edit-${message.id}`}>Edit your question</label>
                        <textarea id={`edit-${message.id}`} autoFocus value={editedPrompt} onChange={event => setEditedPrompt(event.target.value)} onKeyDown={event => { if (event.key === "Escape") setEditingMessageId(null); }} rows={3} />
                        <p>Saving will replace the answers after this question.</p>
                        <div><button type="button" onClick={() => setEditingMessageId(null)}>Cancel</button><button type="submit" disabled={!editedPrompt.trim() || !!generatingId || !!pending}>Save &amp; resend</button></div>
                      </form> : message.sender === "bot" && !message.error
                        ? <MarkdownMessage content={message.content} streaming={message.streaming} citations={message.citations} />
                        : <p>{message.content}</p>}
                      {message.sender === "bot" && !message.streaming && <WebSources sources={message.sources} />}
                      {message.notice && <p role="status" style={{ fontSize: 13, color: "var(--muted-foreground)" }}>{message.notice}</p>}
                      {message.images?.length ? <DocumentImageGallery images={message.images} /> : null}
                      {message.web_images?.length ? <WebImageGallery images={message.web_images} /> : null}
                    </motion.article>
                  ))}
                </AnimatePresence>
              </div>
            )}
            {pending?.id === currentId && (
              <div className="pending-message" role="status">
                <Emblem />
                <span>
                  {pending.kind === "upload"
                    ? uploadStatus || "Reading between the lines…"
                    : "A little thinking in progress…"}
                </span>
                <span className="thinking-dots" aria-hidden="true">
                  •••
                </span>
              </div>
            )}
            <div ref={end} />
          </div>
          <div className="composer-area">
            {resumeAvailable && <div className="answer-resume" role="status">
              <span>Answer stopped.</span>
              <button type="button" onClick={() => void ask(undefined, true)}>
                <Play size={13} aria-hidden="true" /> Resume answer
              </button>
            </div>}
            {!!current?.documents.length && (
              <div className="document-chips">
                {current.documents.map((name, index) => (
                  <span key={`${name}-${index}`}>
                    <FileText size={12} />
                    {name}
                    <Check size={12} />
                  </span>
                ))}
              </div>
            )}
            <form
              className="chat-composer"
              onSubmit={(event) => {
                event.preventDefault();
                void ask(undefined, canResume);
              }}
            >
              <label className="sr-only" htmlFor="question">
                Ask Sonia about your document
              </label>
              <textarea
                id="question"
                ref={textarea}
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={onKeyDown}
                placeholder="What’s on your mind?"
                rows={2}
                disabled={!!pending || !!generatingId || !historyLoaded}
              />
              <div className="composer-controls">
                <button
                  type="button"
                  className="attach-button"
                  onClick={() => fileInput.current?.click()}
                  disabled={!!pending || !!generatingId || !historyLoaded}
                >
                  <Paperclip size={16} />
                  <span>Add a PDF</span>
                </button>
                <span className="composer-hint mono">{answeringHere ? "ANSWERING…" : pending?.kind === "upload" ? "UPLOADING PDF…" : canResume ? "ENTER TO RESUME" : "ENTER TO SEND"}</span>
                <button
                  className="send-button"
                  data-action={composerAction}
                  type={answeringHere ? "button" : "submit"}
                  aria-label={composerActionLabel}
                  onClick={answeringHere ? () => answerController.current?.abort() : undefined}
                  disabled={!answeringHere && ((!input.trim() && !canResume) || !!pending || !!generatingId || !historyLoaded)}
                >
                  {answeringHere ? <span className="composer-stop-mark" aria-hidden="true" /> : canResume ? <Play size={16} fill="currentColor" aria-hidden="true" /> : <ArrowUp size={20} aria-hidden="true" />}
                  <span className="composer-action-tooltip" aria-hidden="true">{composerActionLabel}</span>
                </button>
              </div>
            </form>
            <input
              ref={fileInput}
              type="file"
              accept=".pdf,application/pdf"
              onChange={upload}
              className="sr-only"
              aria-label="Upload PDF"
              tabIndex={-1}
            />
            {fileError && (
              <p className="form-notice" role="alert">
                {fileError}
              </p>
            )}
            <p className="composer-disclaimer">
              A thoughtful assistant, still learning. Always check important
              details in your source.
            </p>
          </div>
        </main>
      </div>
      <AlertDialog.Root open={deleteTarget !== null} onOpenChange={open => { if (!open && !deleting) setDeleteTarget(null); }}>
        <AlertDialog.Portal>
          <AlertDialog.Overlay className={deleteStyles.overlay} />
          <AlertDialog.Content className={deleteStyles.dialog} onEscapeKeyDown={event => { if (deleting) event.preventDefault(); }}>
            <span className={deleteStyles.icon}><Trash2 size={21} /></span>
            <AlertDialog.Title className={deleteStyles.title}>Delete this conversation?</AlertDialog.Title>
            <AlertDialog.Description className={deleteStyles.description}>
              “{deleteTarget?.title}” and all its messages will be removed from your chat history. You can’t undo this action.
            </AlertDialog.Description>
            {deleteError && <p className={deleteStyles.error} role="alert">{deleteError}</p>}
            <div className={deleteStyles.actions}>
              <AlertDialog.Cancel className={deleteStyles.cancel} disabled={deleting}>Cancel</AlertDialog.Cancel>
              <button type="button" className={deleteStyles.confirm} disabled={deleting || pending?.id === deleteTarget?.id}
                onClick={() => { if (deleteTarget) void remove(deleteTarget.id); }}>
                {deleting ? "Deleting…" : "Delete conversation"}
              </button>
            </div>
          </AlertDialog.Content>
        </AlertDialog.Portal>
      </AlertDialog.Root>
    </MotionConfig>
  );
}
