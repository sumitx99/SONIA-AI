"use client";

import { useState } from "react";
import { publicToolCalls } from "@/lib/web-activity";
import { AlertTriangle, Ban, Check, ChevronDown, Globe, Hand, Loader2, Square } from "lucide-react";
import { decideToolCall, handleApiError, type ToolCall, type WebSource } from "@/lib/api";
import styles from "./tool-activity.module.css";

const STATUS: Record<ToolCall["status"], { label: string; Icon: typeof Check }> = {
  awaiting_approval: { label: "Waiting for you", Icon: Hand },
  running: { label: "In progress", Icon: Loader2 },
  done: { label: "Complete", Icon: Check },
  error: { label: "Failed", Icon: AlertTriangle },
  denied: { label: "Declined", Icon: Ban },
  stopped: { label: "Stopped", Icon: Square },
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
export function ToolCalls({ calls: rawCalls, streaming = false }: { calls?: ToolCall[]; streaming?: boolean }) {
  const calls = publicToolCalls(rawCalls);
  if (!calls.length) return null;
  const preparing = streaming && calls.every(call => call.status !== "running" && call.status !== "awaiting_approval");
  return (
    <section className={styles.activity} aria-label="Answer activity" aria-live="polite" aria-relevant="additions text">
      <p className={styles.heading}>Activity</p>
      <ol className={styles.steps}>
        {calls.map(call => {
          const { Icon, label } = STATUS[call.status];
          const title = call.title.replace(/[_-]+/g, " ").replace(/([a-z0-9])([A-Z])/g, "$1 $2");
          const hasArguments = call.arguments && Object.keys(call.arguments).length > 0;
          return <li key={call.id} className={styles.step} data-status={call.status}>
            <span className={styles.marker}><Icon size={13} className={call.status === "running" ? "animate-spin" : undefined} aria-hidden /></span>
            <div className={styles.content}>
              <div className={styles.row}>
                <span className={styles.title}>{call.server !== "Web" && call.status === "running" ? "Using " : ""}{title}</span>
                <span className={styles.status}>{label}</span>
              </div>
              {call.server !== "Web" && <p className={styles.provider}>{call.server}</p>}
              {call.status === "awaiting_approval" ? <ApprovalCard call={call} /> : (hasArguments || call.summary) && (
                <details className={styles.details}>
                  <summary>Details <ChevronDown size={12} aria-hidden /></summary>
                  {hasArguments && (call.server === "Web"
                    ? <div className={styles.raw}>{Object.values(call.arguments!).flat().filter((value): value is string => typeof value === "string").map((value, index) => <p key={index}>{value}</p>)}</div>
                    : <pre className={styles.raw}>{JSON.stringify(call.arguments, null, 2)}</pre>)}
                  {call.summary && <p className={styles.raw}>{call.summary}</p>}
                </details>
              )}
            </div>
          </li>;
        })}
        {preparing && <li className={styles.step} data-status="running">
          <span className={styles.marker}><Loader2 size={13} className="animate-spin" aria-hidden /></span>
          <span className={styles.title}>Preparing answer…</span>
        </li>}
      </ol>
    </section>
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
