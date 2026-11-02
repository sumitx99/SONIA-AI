// lib/api.ts
import { supabase } from "@/lib/supabase";

// Tolerates spaces, quotes and a trailing slash pasted into hosting env settings.
const API_BASE_URL = ((process.env.NEXT_PUBLIC_API_URL ?? "").trim().replace(/^["']|["']$/g, "").trim()
  || "http://localhost:8000").replace(/\/+$/, "");

export class AuthRequiredError extends Error {}

// Every API call carries the signed-in user's access token; the backend scopes data to that user.
async function apiFetch(path: string, init: RequestInit = {}) {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  if (!token) throw new AuthRequiredError("Please sign in to continue");
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });
  if (response.status === 401) {
    // The useSession listener sends the user back to the sign-in page.
    await supabase.auth.signOut();
    throw new AuthRequiredError("Your session has expired. Please sign in again");
  }
  return response;
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
export const uploadPDF = async (file: File, chatId?: string): Promise<UploadResponse> => {
  try {
    const formData = new FormData();
    formData.append("file", file);
    if (chatId) formData.append("chat_id", chatId);

    const response = await apiFetch("/upload", {
      method: "POST",
      body: formData,
    });

    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(
        errorData.detail || `HTTP error! status: ${response.status}`,
      );
    }

    const data = await response.json();
    return data;
  } catch (error) {
    console.error("Upload error:", error);
    throw error;
  }
};

// Send chat message to backend
export const sendMessage = async (query: string, documentIds?: number[]): Promise<ChatResponse> => {
  try {
    const formData = new FormData();
    formData.append("query", query);
    if (documentIds !== undefined) {
      formData.append("scope_documents", "true");
      documentIds.forEach((id) => formData.append("document_ids", String(id)));
    }

    const response = await apiFetch("/chat", {
      method: "POST",
      body: formData,
    });

    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(
        errorData.detail || `HTTP error! status: ${response.status}`,
      );
    }

    const data = await response.json();
    return data;
  } catch (error) {
    console.error("Chat error:", error);
    throw error;
  }
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
