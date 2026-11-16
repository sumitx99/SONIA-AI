"use client";

import { useState, type ComponentPropsWithoutRef } from "react";
import { Check, Copy } from "lucide-react";

const COPIED_MS = 1800;

/**
 * A fenced code block in an answer: a toolbar naming its language with a copy button, and the
 * code kept exactly as written (no wrapping, no ligatures) so text diagrams stay aligned.
 */
export function MarkdownCode({ source, language, ...props }: ComponentPropsWithoutRef<"pre"> & {
  source: string; language: string | null;
}) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    // Copy the source, not the rendered DOM, so every space and tab survives; only the final newline is dropped.
    await navigator.clipboard.writeText(source.replace(/\n$/, ""));
    setCopied(true);
    window.setTimeout(() => setCopied(false), COPIED_MS);
  }

  return (
    <div className="md-code">
      <div className="md-table-toolbar md-code-toolbar">
        <span className="mono">{(language ?? "text").toUpperCase()}</span>
        <button type="button" onClick={copy} aria-label={copied ? "Copied" : "Copy code"}>
          {copied ? <Check size={13} /> : <Copy size={13} />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre {...props} tabIndex={0} />
    </div>
  );
}
