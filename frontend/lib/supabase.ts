// lib/supabase.ts
import { createClient } from "@supabase/supabase-js";

// Env values pasted into hosting dashboards often carry spaces or quotes; strip them.
const clean = (value: string | undefined) => (value ?? "").trim().replace(/^["']|["']$/g, "").trim();

function validUrl(value: string) {
  try {
    const parsed = new URL(value);
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? value.replace(/\/+$/, "") : "";
  } catch {
    return "";
  }
}

const url = validUrl(clean(process.env.NEXT_PUBLIC_SUPABASE_URL));
const anonKey = clean(process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY);

// An invalid URL counts as missing, so a bad value shows the sign-in setup notice
// instead of failing the build while pages are prerendered.
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
