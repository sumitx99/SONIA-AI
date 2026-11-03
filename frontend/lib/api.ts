// lib/api.ts
import { supabase } from "@/lib/supabase";

// Tolerates spaces, quotes and a trailing slash pasted into hosting env settings.
const API_BASE_URL = ((process.env.NEXT_PUBLIC_API_URL ?? "").trim().replace(/^["']|["']$/g, "").trim()
  || "http://localhost:8000").replace(/\/+$/, "");

export class AuthRequiredError extends Error {}

// Every API call carries the signed-in user's access token; the backend scopes data to that user.
async function apiFetch(path: string, init: RequestInit = {}, expectedUserId?: string) {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  if (!token) throw new AuthRequiredError("Please sign in to continue");
  if (expectedUserId && data.session?.user.id !== expectedUserId) {
    throw new AuthRequiredError("The signed-in account changed. Please reopen your conversation.");
  }
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  let response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });
  if (response.status === 401) {
    const refreshed = await supabase.auth.refreshSession();
    if (refreshed.data.session) {
      if (expectedUserId && refreshed.data.session.user.id !== expectedUserId) {
        throw new AuthRequiredError("The signed-in account changed. Please reopen your conversation.");
      }
      headers.set("Authorization", `Bearer ${refreshed.data.session.access_token}`);
      response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });
    }
  }
  if (response.status === 401) {
    // The useSession listener sends the user back to the sign-in page.
    await supabase.auth.signOut();
    throw new AuthRequiredError("Your session has expired. Please sign in again");
  }
  return response;
}

async function responseError(response: Response) {
  const payload = await response.json().catch(() => null);
  const fallback = response.status >= 500
    ? "The document service is starting up or temporarily unavailable. Please try again."
    : `Request failed (${response.status}). Please try again.`;
  return new Error(typeof payload?.detail === "string" ? payload.detail : fallback);
}

/** A tool from one of the user's MCP connections that Sonia used (or asked to use) for an answer. */
export interface ToolCall {
  id: string;
  server: string;
  tool: string;
  title: string;
  status: "awaiting_approval" | "running" | "done" | "error" | "denied";
  arguments?: Record<string, unknown>;
  summary?: string | null;
}

/** A web page Sonia read for an answer. */
export interface WebSource {
  title: string;
  url: string;
}

export interface ChatMessage {
  id: string;
  content: string;
  sender: "user" | "bot";
  error?: boolean;
  images?: ImageAttachment[];
  notice?: string | null;
  streaming?: boolean;
  tool_calls?: ToolCall[];
  sources?: WebSource[];
}

export interface ChatSession {
  id: string;
  title: string;
  messages: ChatMessage[];
  documents: string[];
  documentIds: number[];
  updatedAt?: string;
  recovered?: boolean;
}

export async function loadConversations(userId?: string): Promise<ChatSession[]> {
  const response = await apiFetch("/conversations", {}, userId);
  if (!response.ok) throw await responseError(response);
  return (await response.json()).conversations;
}

export async function saveConversation(chat: ChatSession, userId?: string) {
  const response = await apiFetch(`/conversations/${encodeURIComponent(chat.id)}`, {
    method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: chat.title, messages: chat.messages }),
  }, userId);
  if (!response.ok) throw await responseError(response);
}

export async function deleteConversation(id: string) {
  const response = await apiFetch(`/conversations/${encodeURIComponent(id)}`, { method: "DELETE" });
  if (!response.ok) throw await responseError(response);
}


export interface ImageAttachment {
  image_id: string;
  document_id: number;
  image_number: number;
  page_number: number;
  heading_path: string[];
  /** The figure's own caption from the PDF (e.g. "Figure 2: …"), when it has one. */
  caption: string | null;
  url: string;
  /** Presigned link to the source PDF at this image's page; null when the PDF isn't in R2. */
  source_url?: string | null;
  source_path: string;
  width: number;
  height: number;
  url_expires_in: number;
}

// Types for API responses
export interface UploadResponse {
  success?: boolean;
  file_id: number;
  filename: string;
  chunks_stored: number;
  message?: string;
  images_stored?: number;
  images_status?: "ready" | "disabled" | "failed";
  warnings?: string[];
}

export interface ChatResponse {
  query: string;
  answer: string;
  images?: ImageAttachment[];
  image_notice?: string | null;
  image_status?: string;
}

export interface ApiError {
  detail: string;
  status_code?: number;
}

// Upload PDF file to backend; chatId groups its files under chats/{chatId}/ in storage
export const uploadPDF = async (file: File, chatId?: string, onStatus?: (status: string) => void): Promise<UploadResponse> => {
  if (file.size > 25 * 1024 * 1024) throw new Error("Please upload a PDF smaller than 25 MB.");
  const requestId = crypto.randomUUID();
  for (let attempt = 0; attempt < 3; attempt++) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 180_000);
  try {
    const formData = new FormData();
    formData.append("file", file);
    if (chatId) formData.append("chat_id", chatId);
    formData.append("request_id", requestId);
    onStatus?.(attempt ? "Reconnecting and retrying your upload…" : "Reading your PDF. The service may take a minute to wake up…");

    const response = await apiFetch("/upload", {
      method: "POST",
      body: formData,
      signal: controller.signal,
    });

    if (!response.ok) {
      if (attempt < 2 && [429, 500, 502, 503, 504].includes(response.status)) {
        onStatus?.("The document service is busy. Retrying automatically…");
        await new Promise((resolve) => setTimeout(resolve, 2000 * (attempt + 1)));
        continue;
      }
      throw await responseError(response);
    }

    const data = await response.json();
    return data;
  } catch (error) {
    if (attempt < 2 && (error instanceof TypeError || (error instanceof Error && error.name === "AbortError"))) {
      await new Promise((resolve) => setTimeout(resolve, 2000 * (attempt + 1)));
      continue;
    }
    console.error("Upload error:", error);
    throw error;
  } finally {
    clearTimeout(timer);
  }
  }
  throw new Error("The document service could not be reached. Please try again.");
};

// Send chat message to backend
export const sendMessage = async (query: string, documentIds?: number[], history: { sender: "user" | "bot"; content: string }[] = []): Promise<ChatResponse> => {
  try {
    const formData = new FormData();
    formData.append("query", query);
    formData.append("history", JSON.stringify(history));
    if (documentIds !== undefined) {
      formData.append("scope_documents", "true");
      documentIds.forEach((id) => formData.append("document_ids", String(id)));
    }

    const response = await apiFetch("/chat", {
      method: "POST",
      body: formData,
    });

    if (!response.ok) {
      throw await responseError(response);
    }

    const data = await response.json();
    return data;
  } catch (error) {
    console.error("Chat error:", error);
    throw error;
  }
};

export interface StreamHandlers {
  /** Images and status, sent once before the text. */
  onMeta?: (meta: Omit<ChatResponse, "query" | "answer">) => void;
  /** Each new piece of the answer, in order. */
  onDelta: (text: string) => void;
  /** A tool call starting, waiting for approval, or finishing (same id, newer status). */
  onToolCall?: (call: ToolCall) => void;
  /** Web pages the answer used, once at the end. */
  onSources?: (sources: WebSource[]) => void;
}

/**
 * Streams an answer from /chat/stream (server-sent events). Resolves when the answer is
 * complete; rejects if nothing usable arrived. `cutOff` is true when the stream broke
 * part-way, after some text had already been shown.
 */
export const streamMessage = async (
  query: string, documentIds: number[] | undefined, handlers: StreamHandlers,
  history: { sender: "user" | "bot"; content: string }[] = [],
): Promise<{ cutOff: boolean }> => {
  const formData = new FormData();
  formData.append("query", query);
  formData.append("history", JSON.stringify(history));
  if (documentIds !== undefined) {
    formData.append("scope_documents", "true");
    documentIds.forEach((id) => formData.append("document_ids", String(id)));
  }
  const response = await apiFetch("/chat/stream", { method: "POST", body: formData });

  // An API deployed before streaming existed: fall back to the one-shot endpoint.
  if (response.status === 404) {
    const { answer, ...meta } = await sendMessage(query, documentIds, history);
    handlers.onMeta?.(meta);
    handlers.onDelta(answer);
    return { cutOff: false };
  }
  if (!response.ok || !response.body) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
  }

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  let wroteText = false;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    // Events are separated by a blank line; keep a trailing partial event for the next read.
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      let event = "message";
      let data = "";
      for (const line of frame.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      if (!data) continue;
      const payload = JSON.parse(data);
      if (event === "meta") handlers.onMeta?.(payload);
      else if (event === "tool_call") handlers.onToolCall?.(payload);
      else if (event === "sources") handlers.onSources?.(payload.sources);
      else if (event === "delta") {
        wroteText = true;
        handlers.onDelta(payload.text);
      } else if (event === "done") return { cutOff: false };
      else if (event === "error") {
        if (!wroteText) throw new Error(payload.detail);
        return { cutOff: true };
      }
    }
  }
  // The connection closed without a "done" event.
  if (!wroteText) throw new Error("The answer didn't arrive");
  return { cutOff: true };
};

// Renew expired image links without asking the model to generate another answer.
export const refreshDocumentImage = async (documentId: number, imageId: string): Promise<ImageAttachment> => {
  const response = await apiFetch(`/documents/${documentId}/images/${encodeURIComponent(imageId)}`);
  if (!response.ok) throw new Error("The image could not be reloaded. Please try again.");
  return response.json();
};

// Health check endpoint
export const healthCheck = async (): Promise<{
  status: string;
  message: string;
}> => {
  try {
    const response = await fetch(`${API_BASE_URL}/health`);

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const data = await response.json();
    return data;
  } catch (error) {
    console.error("Health check error:", error);
    throw error;
  }
};

// Generic API error handler
export const handleApiError = (error: unknown): string => {
  if (error instanceof Error) {
    return error.message;
  }
  return "An unexpected error occurred";
};

export interface AccountProfile {
  display_name: string;
  bio: string;
  reduce_motion: boolean;
  compact_mode: boolean;
  avatar_url: string | null;
  avatar_expires_at: number | null;
}
export type ProfileDetails = Pick<AccountProfile, "display_name" | "bio" | "reduce_motion" | "compact_mode">;

export async function loadProfile(userId: string): Promise<AccountProfile> {
  const response = await apiFetch("/profile", { cache: "no-store" }, userId);
  if (!response.ok) throw await responseError(response);
  return response.json();
}
export async function updateProfile(details: ProfileDetails, userId: string): Promise<AccountProfile> {
  const response = await apiFetch("/profile", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(details) }, userId);
  if (!response.ok) throw await responseError(response);
  return response.json();
}
export async function uploadAvatar(file: File, userId: string): Promise<AccountProfile> {
  const body = new FormData(); body.append("file", file);
  const response = await apiFetch("/profile/avatar", { method: "POST", body }, userId);
  if (!response.ok) throw await responseError(response);
  return response.json();
}
export async function deleteAvatar(userId: string): Promise<AccountProfile> {
  const response = await apiFetch("/profile/avatar", { method: "DELETE" }, userId);
  if (!response.ok) throw await responseError(response);
  return response.json();
}

// Approve or decline a tool call an answer is waiting on.
export const decideToolCall = async (approvalId: string, approve: boolean) => {
  const response = await apiFetch(`/chat/approvals/${encodeURIComponent(approvalId)}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ approve }),
  });
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || "That request has expired");
};

// --- MCP connections: servers whose tools Sonia may use in chat ---

export type ToolPolicy = "allow" | "ask" | "off";

export interface McpTool {
  name: string;
  title: string;
  description: string;
  read_only: boolean;
  destructive: boolean;
  policy: ToolPolicy;
}

export interface McpConnection {
  id: string;
  name: string;
  url: string;
  auth_type: "none" | "header" | "oauth";
  enabled: boolean;
  last_error: string | null;
  created_at: string;
  tools: McpTool[];
}

async function connectionsRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(`/mcp-connections${path}`, {
    ...init, headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (!response.ok) {
    const detail = (await response.json().catch(() => ({}))).detail;
    throw new Error(typeof detail === "string" ? detail : "The request couldn’t be completed");
  }
  return (response.status === 204 ? undefined : await response.json()) as T;
}

export const listMcpConnections = async () =>
  (await connectionsRequest<{ connections: McpConnection[] }>("")).connections;

export const addMcpConnection = (input: { name: string; url: string; auth_type: "none" | "header";
  header_name?: string; header_value?: string }) =>
  connectionsRequest<McpConnection>("", { method: "POST", body: JSON.stringify(input) });

export const refreshMcpConnection = (id: string) =>
  connectionsRequest<McpConnection>(`/${id}/refresh`, { method: "POST" });

export const updateMcpConnection = (id: string, changes: { name?: string; enabled?: boolean;
  tool_policies?: Record<string, ToolPolicy> }) =>
  connectionsRequest<McpConnection>(`/${id}`, { method: "PATCH", body: JSON.stringify(changes) });

export const deleteMcpConnection = (id: string) =>
  connectionsRequest<void>(`/${id}`, { method: "DELETE" });

// Sign in to an MCP server that uses OAuth: open `authorization_url`, then poll the status.
export const startMcpOAuth = (input: { name: string; url: string }) =>
  connectionsRequest<{ flow_id: string; authorization_url: string }>("/oauth/start", {
    method: "POST", body: JSON.stringify(input),
  });

export const mcpOAuthStatus = (flowId: string) =>
  connectionsRequest<{ status: "pending" | "done" | "error"; error: string | null; connection?: McpConnection }>(
    `/oauth/status/${encodeURIComponent(flowId)}`);
