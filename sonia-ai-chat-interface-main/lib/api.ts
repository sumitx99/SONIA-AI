// lib/api.ts
const API_BASE_URL = 'http://localhost:8000';

// Types for API responses
export interface UploadResponse {
  success: boolean;
  file_id: number;
  filename: string;
  chunks_stored: number;
  message: string;
}

export interface ChatResponse {
  query: string;
  answer: string;
}

export interface ApiError {
  detail: string;
  status_code?: number;
}

// Upload PDF file to backend
export const uploadPDF = async (file: File): Promise<UploadResponse> => {
  try {
    const formData = new FormData();
    formData.append('file', file);
    
    const response = await fetch(`${API_BASE_URL}/upload`, {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
    }

    const data = await response.json();
    return data;
  } catch (error) {
    console.error('Upload error:', error);
    throw error;
  }
};

// Send chat message to backend
export const sendMessage = async (query: string): Promise<ChatResponse> => {
  try {
    const formData = new FormData();
    formData.append('query', query);
    
    const response = await fetch(`${API_BASE_URL}/chat`, {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
    }

    const data = await response.json();
    return data;
  } catch (error) {
    console.error('Chat error:', error);
    throw error;
  }
};

// Health check endpoint
export const healthCheck = async (): Promise<{ status: string; message: string }> => {
  try {
    const response = await fetch(`${API_BASE_URL}/health`);
    
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const data = await response.json();
    return data;
  } catch (error) {
    console.error('Health check error:', error);
    throw error;
  }
};

// Generic API error handler
export const handleApiError = (error: unknown): string => {
  if (error instanceof Error) {
    return error.message;
  }
  return 'An unexpected error occurred';
};