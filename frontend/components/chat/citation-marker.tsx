"use client";

import { useState } from "react";
import * as Popover from "@radix-ui/react-popover";
import { AlertTriangle, BadgeCheck, CircleHelp, ExternalLink, FileText, Globe, Loader2, Wrench } from "lucide-react";
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

/** Found in the source, checked and not found, or not checkable because the page could not be read. */
function checkState(citation: Citation) {
  if (citation.verified) return { className: "", label: "", Icon: BadgeCheck, text: "Found in source", tone: styles.verified };
  if (citation.source_unreadable) return { className: styles.unchecked, label: " (could not be checked)", Icon: CircleHelp,
    text: "Page couldn’t be opened to check this quote", tone: styles.unknown };
  return { className: styles.unverified, label: " (not verified)", Icon: AlertTriangle, text: "Not found in source", tone: styles.warning };
}

/**
 * A numbered citation in an answer. Opens a card with the source and the exact quote, marked
 * verified only when the backend found that quote in the source, and neutral when the source
 * could not be read to check it. While the answer is still streaming the number shows without details.
 */
export function CitationMarker({ n, citation, pending }: { n: number; citation?: Citation; pending: boolean }) {
  if (!citation) {
    return <sup className={`${styles.marker} ${pending ? styles.pending : styles.missing}`}
                title={pending ? undefined : "No source was given for this citation"}>{n}</sup>;
  }
  const Icon = KIND[citation.kind];
  const check = checkState(citation);
  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <button type="button" className={`${styles.marker} ${check.className}`}
                aria-label={`Source ${n}: ${citation.title}${check.label}`}>
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
            <span className={check.tone}><check.Icon size={13} aria-hidden /> {check.text}</span>
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
