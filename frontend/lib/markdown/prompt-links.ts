export type PromptSegment = { text: string; url?: string };

const URL_PATTERN = /https?:\/\/[^\s<>"']+/gi;
const TRAILING_PUNCTUATION = /[.,!?;:)}\]]+$/;

export function safePromptUrl(value: string): string | null {
  try {
    const parsed = new URL(value);
    if ((parsed.protocol === "http:" || parsed.protocol === "https:") && parsed.hostname) return parsed.href;
  } catch {
    // Malformed URLs are plain text, never clickable links.
  }
  return null;
}

/** Split prompt text into ordinary text and safe HTTP(S) URL segments. */
export function promptSegments(value: string): PromptSegment[] {
  const segments: PromptSegment[] = [];
  let cursor = 0;

  for (const match of value.matchAll(URL_PATTERN)) {
    const raw = match[0];
    const start = match.index ?? 0;
    const url = raw.replace(TRAILING_PUNCTUATION, "");
    if (!url) continue;
    if (!safePromptUrl(url)) continue;

    if (start > cursor) segments.push({ text: value.slice(cursor, start) });
    segments.push({ text: url, url });
    cursor = start + url.length;
  }

  if (cursor < value.length || segments.length === 0) segments.push({ text: value.slice(cursor) });
  return segments;
}
