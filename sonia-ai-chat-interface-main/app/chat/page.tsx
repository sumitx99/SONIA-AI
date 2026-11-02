"use client";

import {
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type KeyboardEvent,
} from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion, MotionConfig } from "motion/react";
import {
  ArrowUp,
  ArrowUpRight,
  Check,
  FileText,
  LogOut,
  Menu,
  MessageSquare,
  Paperclip,
  Pencil,
  Plus,
  Trash2,
  X,
} from "lucide-react";
import { Brand, Emblem } from "@/components/brand";
import { DocumentImageGallery } from "@/components/document-image";
import { MarkdownMessage } from "@/components/markdown-message";
import { sendMessage, uploadPDF, handleApiError, type ImageAttachment } from "@/lib/api";
import { supabase } from "@/lib/supabase";
import { useSession } from "@/lib/use-session";

interface Message {
  id: string;
  content: string;
  sender: "user" | "bot";
  error?: boolean;
  images?: ImageAttachment[];
  notice?: string | null;
}
interface ChatSession {
  id: string;
  title: string;
  messages: Message[];
  documents: string[];
  documentIds: number[];
}

const suggestions = [
  "Summarize the key ideas",
  "What are the main takeaways?",
  "Explain the document in simple terms",
];

export default function SoniaChatInterface() {
  const router = useRouter();
  const { session, ready } = useSession();
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState<{
    id: string;
    kind: "answer" | "upload";
  } | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [fileError, setFileError] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const end = useRef<HTMLDivElement>(null);
  const busy = useRef(false);
  const current = sessions.find((session) => session.id === currentId);
  const messages = current?.messages ?? [];

  // Signed-out visitors (or an expired session) go to the sign-in page.
  useEffect(() => {
    if (ready && !session) router.replace("/auth?next=/chat");
  }, [ready, session, router]);

  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "instant", block: "end" });
  }, [messages.length, pending]);

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

  async function ask() {
    const query = input.trim();
    if (!query || busy.current) return;
    busy.current = true;
    const id = currentId ?? newChat();
    append(id, { id: crypto.randomUUID(), content: query, sender: "user" });
    if (!messages.length)
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
    try {
      const response = await sendMessage(query, current?.documentIds ?? []);
      append(id, {
        id: crypto.randomUUID(),
        content: response.answer,
        sender: "bot",
        images: response.images,
        notice: response.image_notice,
      });
    } catch (error) {
      append(id, {
        id: crypto.randomUUID(),
        content: `I couldn’t get an answer. ${handleApiError(error)}. Please check the connection and try again.`,
        sender: "bot",
        error: true,
      });
    } finally {
      busy.current = false;
      setPending(null);
    }
  }

  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || busy.current) return;
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setFileError("Please choose a PDF document.");
      return;
    }
    setFileError("");
    busy.current = true;
    const id = currentId ?? newChat();
    setPending({ id, kind: "upload" });
    try {
      const response = await uploadPDF(file, id);
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
        content: `“${file.name}” is ready.${response.images_status === "ready" ? ` ${response.images_stored ?? 0} images are available—ask to see an image or specify a page.` : ""} What would you like to discover?`,
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

  function remove(id: string) {
    setSessions((previous) => previous.filter((session) => session.id !== id));
    if (currentId === id) {
      setCurrentId(null);
      setInput("");
      setFileError("");
    }
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
    <MotionConfig reducedMotion="user">
      <div className="chat-app">
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
          <button className="button button-ink new-chat" onClick={newChat}>
            <Plus size={16} /> A fresh conversation
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
                        onClick={() => remove(session.id)}
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
            <Emblem />
            <p>
              A little space
              <br />
              <em>for big ideas.</em>
            </p>
            <span className="mono">HISTORY LASTS FOR THIS VISIT</span>
            <div className="account-user">
              <span>Signed in as</span>
              <strong>{session.user.email}</strong>
              <button type="button" className="text-link" onClick={signOut}>
                <LogOut size={14} /> Sign out
              </button>
            </div>
            <Link href="/" className="sidebar-home">
              Back to Sonia <ArrowUpRight size={14} />
            </Link>
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
              <span className="room-label">The reading room</span>
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
            {!messages.length ? (
              <motion.div
                className="chat-welcome"
                initial={{ opacity: 0, y: 15 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5 }}
              >
                <Emblem />
                <p className="eyebrow">MAKE YOURSELF AT HOME.</p>
                <h1>
                  A little room
                  <br />
                  <em>for clarity.</em>
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
                      </div>
                      {message.sender === "bot" && !message.error
                        ? <MarkdownMessage content={message.content} />
                        : <p>{message.content}</p>}
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
                    ? "Reading between the lines…"
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
                disabled={!!pending}
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
    </MotionConfig>
  );
}
