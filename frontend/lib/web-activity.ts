import type { ToolCall } from "@/lib/api";

/** Older saved chats may contain provider-routing diagnostics. Keep the UI task-focused. */
export function publicToolCalls(calls: ToolCall[] = []): ToolCall[] {
  return calls.flatMap(call => {
    if (call.server !== "Web") return [call];
    if (["web-backup", "web-search-unavailable"].includes(call.id)) return [];
    const reading = call.tool === "url_context";
    const title = call.status === "running" ? (reading ? "Reading web pages" : "Searching the web")
      : call.status === "error" ? (reading ? "Page could not be read" : "Web search unavailable")
      : (reading ? "Web pages read" : "Web search complete");
    const summary = call.status === "error" ? "This request could not be completed. Please try again later."
      : /^\d+ source links returned\.$/.test(call.summary || "") ? call.summary : undefined;
    const args = Object.fromEntries(Object.entries(call.arguments || {}).filter(([name]) => ["query", "queries", "url", "urls"].includes(name)));
    return [{ ...call, title, summary, arguments: args }];
  });
}
