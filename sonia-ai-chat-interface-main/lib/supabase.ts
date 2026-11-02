// lib/supabase.ts
import { createClient } from "@supabase/supabase-js";

const url = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "";

export const supabaseConfigured = Boolean(url && anonKey);

// The session lives in localStorage and the access token refreshes itself.
// Placeholders keep the import from throwing; the auth page explains what is missing.
export const supabase = createClient(url || "http://localhost:54321", anonKey || "missing-anon-key", {
  auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
});

// Only same-site paths are allowed as a post-login destination.
export function safeNext(value: string | null | undefined, fallback = "/chat") {
  return value && value.startsWith("/") && !value.startsWith("//") ? value : fallback;
}
