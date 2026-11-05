import type { ToolCall } from "@/lib/api";

/** Older saved chats may contain provider-routing diagnostics. Keep the UI task-focused. */
export function publicToolCalls(calls: ToolCall[] = []): ToolCall[] {
  return calls.flatMap(call => {
    if (call.server !== "Web") return [call];
    if (["web-backup", "web-search-unavailable"].includes(call.id)) return [];
    const reading = call.tool === "url_context" || call.tool === "read_web_page";
    const images = call.tool === "image_search" || call.tool === "google_search_images";
    const title = call.status === "running" ? (images ? "Searching web images" : reading ? "Reading web pages" : "Searching the web")
      : call.status === "error" ? (images ? "Web images unavailable" : reading ? "Page could not be read" : "Web search unavailable")
      : (images ? "Web image search complete" : reading ? "Web pages read" : "Web search complete");
    const summary = call.status === "error" ? "This request could not be completed. Please try again later."
      : /^\d+ source links returned\.$/.test(call.summary || "") ? call.summary : undefined;
    const args = Object.fromEntries(Object.entries(call.arguments || {}).filter(([name]) => ["query", "queries", "url", "urls"].includes(name)));
    return [{ ...call, title, summary, arguments: args }];
  });
}
