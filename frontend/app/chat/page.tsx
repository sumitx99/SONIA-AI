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
  Trash2,
  X,
} from "lucide-react";
import { Brand, Emblem } from "@/components/brand";
import { AccountMenu } from "@/components/account/account-menu";
import { DocumentImageGallery } from "@/components/chat/document-image";
import { MarkdownMessage } from "@/components/chat/markdown-message";
import { ToolCalls, WebSources } from "@/components/chat/tool-calls";
import { streamMessage, uploadPDF, deleteConversation, handleApiError, type ImageAttachment,
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
  const toolStepCount = messages[messages.length - 1]?.tool_calls?.length ?? 0;

  useEffect(() => { setCurrentId(null); setDeleteTarget(null); }, [session?.user.id]);

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

  function append(id: string, message: Message) {
    setSessions((previous) =>
      previous.map((session) =>
        session.id === id
          ? { ...session, messages: [...session.messages, message] }
          : session,
      ),
    );
  }

  async function ask(replacement?: { messageId: string; content: string }) {
    const query = (replacement?.content ?? input).trim();
    if (!query || busy.current || !historyLoaded) return;
    if (replacement && !messages.some(m => m.id === replacement.messageId && m.sender === "user")) return;
    busy.current = true;
    const id = currentId ?? newChat();
    const branch = replacement ? editConversation(messages, replacement.messageId, query) : null;
    const before = branch?.before ?? messages;
    if (branch) {
      setSessions(previous => previous.map(chat => chat.id === id ? { ...chat, messages: branch.messages } : chat));
    } else {
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
    setInput("");
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
        onCitations: (answer, citations) => {
          text = answer;
          update({ content: answer, citations });
        },
      }, conversationHistory(before));
      toolCalls = toolCalls.map(call => call.status === "running" ? { ...call, status: cutOff ? "error" as const : "done" as const } : call);
      update({
        streaming: false, tool_calls: toolCalls,
        ...(cutOff && { notice: "The answer was cut off part-way. Ask again to get the rest." }),
      });
    } catch (error) {
      if (started) {
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
        id: crypto.randomUUID(),
        content: `“${file.name}” is ready.${response.images_status === "ready" ? ` ${response.images_stored ?? 0} image${response.images_stored === 1 ? " is" : "s are"} available—ask to see an image or specify a page.` : ""} What would you like to discover?`,
        sender: "bot",
        notice: response.warnings?.join(" ") || (response.images_status === "disabled"
          ? "Image extraction is unavailable until image storage is configured." : null),
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
      void ask();
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
                      {message.sender === "bot" && <ToolCalls calls={message.tool_calls} />}
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
                void ask();
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
                disabled={!!pending || !historyLoaded}
              />
              <div className="composer-controls">
                <button
                  type="button"
                  className="attach-button"
                  onClick={() => fileInput.current?.click()}
                  disabled={!!pending}
                >
                  <Paperclip size={16} />
                  <span>Add a PDF</span>
                </button>
                <span className="composer-hint mono">ENTER TO SEND</span>
                <button
                  className="send-button"
                  type="submit"
                  aria-label="Send message"
                  disabled={!input.trim() || !!pending}
                >
                  <ArrowUp size={20} />
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
