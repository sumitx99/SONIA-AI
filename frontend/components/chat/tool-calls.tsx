"use client";

import { useState } from "react";
import { AlertTriangle, Ban, Check, Globe, Hand, Loader2, Wrench } from "lucide-react";
import { decideToolCall, handleApiError, type ToolCall, type WebSource } from "@/lib/api";

const STATUS: Record<ToolCall["status"], { label: string; Icon: typeof Check }> = {
  awaiting_approval: { label: "Waiting for you", Icon: Hand },
  running: { label: "Running", Icon: Loader2 },
  done: { label: "Done", Icon: Check },
  error: { label: "Failed", Icon: AlertTriangle },
  denied: { label: "Declined", Icon: Ban },
};

function ApprovalCard({ call }: { call: ToolCall }) {
  const [busy, setBusy] = useState<"allow" | "deny" | null>(null);
  const [error, setError] = useState("");

  async function decide(approve: boolean) {
    setBusy(approve ? "allow" : "deny");
    setError("");
    try {
      // The answer's stream then reports the call as running/declined.
      await decideToolCall(call.id, approve);
    } catch (failure) {
      setError(handleApiError(failure));
      setBusy(null);
    }
  }

  const args = Object.entries(call.arguments ?? {});
  return (
    <div className="tool-approval" role="group" aria-label={`Approve ${call.title}`}>
      <p>
        Sonia wants to use <strong>{call.title}</strong> on <strong>{call.server}</strong>.
      </p>
      {args.length > 0 && (
        <dl className="tool-arguments">
          {args.map(([key, value]) => (
            <div key={key}>
              <dt>{key}</dt>
              <dd>{typeof value === "string" ? value : JSON.stringify(value)}</dd>
            </div>
          ))}
        </dl>
      )}
      {error && <p className="tool-error" role="alert">{error}</p>}
      <div className="tool-approval-actions">
        <button type="button" onClick={() => decide(false)} disabled={busy !== null}>
          {busy === "deny" ? <Loader2 size={13} className="animate-spin" /> : <Ban size={13} />} Deny
        </button>
        <button type="button" className="is-primary" onClick={() => decide(true)} disabled={busy !== null}>
          {busy === "allow" ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} />} Allow
        </button>
      </div>
    </div>
  );
}

/** The tools Sonia used for an answer, and approval prompts for ones that need consent. */
export function ToolCalls({ calls }: { calls?: ToolCall[] }) {
  if (!calls?.length) return null;
  return (
    <div className="tool-calls" aria-label="Tools used for this answer">
      {calls.map((call) =>
        call.status === "awaiting_approval" ? <ApprovalCard key={call.id} call={call} /> : (
          <details key={call.id} className={`tool-chip is-${call.status}`}>
            <summary>
              <Wrench size={12} aria-hidden />
              <span className="tool-chip-name">{call.server} › {call.title}</span>
              <span className="tool-chip-status">
                {(() => { const { Icon, label } = STATUS[call.status]; return <><Icon size={12}
                  className={call.status === "running" ? "animate-spin" : undefined} aria-hidden />{label}</>; })()}
              </span>
            </summary>
            {call.arguments && Object.keys(call.arguments).length > 0 && (
              <pre className="tool-chip-detail">{JSON.stringify(call.arguments, null, 2)}</pre>
            )}
            {call.summary && <p className="tool-chip-detail">{call.summary}</p>}
          </details>
        ))}
    </div>
  );
}

function hostOf(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

/** The web pages Sonia read for an answer. */
export function WebSources({ sources }: { sources?: WebSource[] }) {
  const links = sources?.filter((source) => /^https?:\/\//.test(source.url));
  if (!links?.length) return null;
  return (
    <nav className="web-sources" aria-label="Web sources for this answer">
      <span className="web-sources-label mono"><Globe size={12} aria-hidden /> Sources</span>
      {links.map((source) => (
        <a key={source.url} href={source.url} target="_blank" rel="noopener noreferrer nofollow"
           title={source.url}>
          <span className="web-source-title">{source.title || hostOf(source.url)}</span>
          <span className="web-source-host">{hostOf(source.url)}</span>
        </a>
      ))}
    </nav>
  );
}
