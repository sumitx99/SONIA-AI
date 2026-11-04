"use client";

import { useState } from "react";
import * as Popover from "@radix-ui/react-popover";
import { AlertTriangle, BadgeCheck, ExternalLink, FileText, Globe, Loader2, Wrench } from "lucide-react";
import { handleApiError, loadDocumentSource, type Citation } from "@/lib/api";
import styles from "./citation-marker.module.css";

const KIND = { document: FileText, web: Globe, tool: Wrench, unknown: AlertTriangle } as const;

function hostOf(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

/** Opens one of the user's PDFs (the API needs the sign-in token, so it is fetched, not linked). */
function OpenDocument({ documentId }: { documentId: number }) {
  const [state, setState] = useState<"idle" | "opening" | string>("idle");
  async function open() {
    setState("opening");
    const tab = window.open("", "_blank");
    try {
      const url = URL.createObjectURL(await loadDocumentSource(documentId));
      if (tab) tab.location.href = url;
      else window.open(url, "_blank");
      setState("idle");
    } catch (error) {
      tab?.close();
      setState(handleApiError(error));
    }
  }
  return (
    <>
      <button type="button" className={styles.link} onClick={open} disabled={state === "opening"}>
        {state === "opening" ? <Loader2 size={12} className="animate-spin" /> : <ExternalLink size={12} />} Open PDF
      </button>
      {state !== "idle" && state !== "opening" && <p className={styles.error} role="alert">{state}</p>}
    </>
  );
}

/**
 * A numbered citation in an answer. Opens a card with the source and the exact quote, marked
 * verified only when the backend found that quote in the source. While the answer is still
 * streaming the number shows without details.
 */
export function CitationMarker({ n, citation, pending }: { n: number; citation?: Citation; pending: boolean }) {
  if (!citation) {
    return <sup className={`${styles.marker} ${pending ? styles.pending : styles.missing}`}
                title={pending ? undefined : "No source was given for this citation"}>{n}</sup>;
  }
  const Icon = KIND[citation.kind];
  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <button type="button" className={`${styles.marker} ${citation.verified ? "" : styles.unverified}`}
                aria-label={`Source ${n}: ${citation.title}${citation.verified ? "" : " (not verified)"}`}>
          {n}
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content className={styles.card} side="top" align="start" sideOffset={6} collisionPadding={12}>
          <header className={styles.header}>
            <Icon size={13} aria-hidden />
            <span className={styles.title}>{citation.title}</span>
          </header>
          {citation.url && <p className={styles.host}>{hostOf(citation.url)}</p>}
          <blockquote className={styles.quote}>“{citation.quote}”</blockquote>
          <footer className={styles.footer}>
            {citation.verified
              ? <span className={styles.verified}><BadgeCheck size={13} aria-hidden /> Found in source</span>
              : <span className={styles.warning}><AlertTriangle size={13} aria-hidden /> Not found in source</span>}
            {citation.url && (
              <a className={styles.link} href={citation.url} target="_blank" rel="noopener noreferrer nofollow">
                <ExternalLink size={12} /> Open page
              </a>
            )}
            {citation.kind === "document" && citation.document_id != null && <OpenDocument documentId={citation.document_id} />}
          </footer>
          <Popover.Arrow className={styles.arrow} />
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
