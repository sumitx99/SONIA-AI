"use client";

import { useMemo, useRef, useState, type ComponentPropsWithoutRef } from "react";
import ReactMarkdown, { type Components, type ExtraProps } from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { Check, Copy, FileCode2 } from "lucide-react";
import "katex/dist/katex.min.css";
import remarkNoImages from "@/lib/markdown/remark-no-images";
import { GraphComponent } from "@/components/chat/graph-component";

/** Readable plain text for a KaTeX formula, e.g. "O(n^2 \cdot d)" → "O(n^2 · d)". */
function texToText(tex: string) {
  return tex
    .replace(/\\(cdot|times)/g, (_, op) => (op === "cdot" ? "·" : "×"))
    .replace(/\\sqrt\{([^}]*)\}/g, "√($1)")
    // No \b here: in "\log_k" the "_" counts as a word character.
    .replace(/\\(log|ln|exp|sin|cos|max|min)(?![a-zA-Z])/g, "$1")
    .replace(/\\[a-zA-Z]+/g, "")
    .replace(/[{}]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * A cell's text with each formula (KaTeX keeps its TeX source) either as readable text,
 * for spreadsheets, or as $TeX$, for Markdown.
 */
function cellText(cell: HTMLTableCellElement, math: "text" | "tex" = "text") {
  const copy = cell.cloneNode(true) as HTMLElement;
  copy.querySelectorAll(".katex").forEach((formula) => {
    const tex = formula.querySelector('annotation[encoding="application/x-tex"]')?.textContent ?? "";
    formula.replaceWith(document.createTextNode(math === "tex" ? `$${tex}$` : texToText(tex)));
  });
  return (copy.textContent ?? "").replace(/\s+/g, " ").trim();
}

const escapeHtml = (text: string) =>
  text.replace(/[&<>"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[char]!);

function tableRows(table: HTMLTableElement, math: "text" | "tex" = "text") {
  return [...table.rows].map((row) => [...row.cells].map((cell) => cellText(cell, math)));
}

function MarkdownTable(props: ComponentPropsWithoutRef<"table">) {
  const ref = useRef<HTMLTableElement>(null);
  const [copied, setCopied] = useState<"table" | "markdown" | null>(null);

  function flash(kind: "table" | "markdown") {
    setCopied(kind);
    window.setTimeout(() => setCopied((current) => (current === kind ? null : current)), 1800);
  }

  // Copies HTML and tab-separated text together, so pasting into Sheets, Excel or Docs
  // produces a real table while plain-text editors get aligned columns.
  async function copyTable() {
    if (!ref.current) return;
    const rows = tableRows(ref.current);
    const tsv = rows.map((cells) => cells.join("\t")).join("\n");
    const html = `<table><thead><tr>${rows[0].map((c) => `<th>${escapeHtml(c)}</th>`).join("")}</tr></thead>`
      + `<tbody>${rows.slice(1).map((cells) => `<tr>${cells.map((c) => `<td>${escapeHtml(c)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
    try {
      await navigator.clipboard.write([new ClipboardItem({
        "text/html": new Blob([html], { type: "text/html" }),
        "text/plain": new Blob([tsv], { type: "text/plain" }),
      })]);
    } catch {
      await navigator.clipboard.writeText(tsv);
    }
    flash("table");
  }

  async function copyMarkdown() {
    if (!ref.current) return;
    const [header, ...body] = tableRows(ref.current, "tex");
    const line = (cells: string[]) => `| ${cells.map((c) => c.replace(/\|/g, "\\|")).join(" | ")} |`;
    await navigator.clipboard.writeText(
      [line(header), line(header.map(() => "---")), ...body.map(line)].join("\n"));
    flash("markdown");
  }

  return (
    <div className="md-table">
      <div className="md-table-toolbar">
        <span className="mono">TABLE</span>
        <button type="button" onClick={copyMarkdown} aria-label="Copy table as Markdown">
          {copied === "markdown" ? <Check size={13} /> : <FileCode2 size={13} />}
          {copied === "markdown" ? "Copied" : "Markdown"}
        </button>
        <button type="button" onClick={copyTable} aria-label="Copy table for spreadsheets and documents">
          {copied === "table" ? <Check size={13} /> : <Copy size={13} />}
          {copied === "table" ? "Copied" : "Copy table"}
        </button>
      </div>
      <div className="md-table-scroll" tabIndex={0} role="region" aria-label="Table, scrolls sideways">
        <table ref={ref} {...props} />
      </div>
    </div>
  );
}

/** The JSON inside a ```plotly code block, or null for any other block. */
function plotlySource(node: ExtraProps["node"]): string | null {
  const code = node?.children[0];
  if (!code || code.type !== "element" || code.tagName !== "code") return null;
  const classes = code.properties?.className;
  if (!Array.isArray(classes) || !classes.includes("language-plotly")) return null;
  return code.children.map((child) => (child.type === "text" ? child.value : "")).join("");
}

function markdownComponents(streaming: boolean): Components {
  return {
    // Only backend-verified attachments may render images. Model URLs can be invented,
    // expired or relative paths from a PDF, and otherwise produce broken duplicates.
    img: () => null,
    table: ({ node: _node, ...props }) => <MarkdownTable {...props} />,
    a: ({ node: _node, ...props }) => <a {...props} target="_blank" rel="noreferrer nofollow" />,
    // A ```plotly block is a chart the model drew from the answer's numbers.
    pre: ({ node, ...props }) => {
      const chart = plotlySource(node);
      return chart === null ? <pre {...props} /> : <GraphComponent source={chart} streaming={streaming} />;
    },
  };
}

/**
 * Renders an answer written in GitHub-flavoured Markdown with $…$ / $$…$$ maths.
 * Raw HTML in the text is dropped, never rendered (model output is untrusted).
 * While `streaming`, a caret follows the last line of text.
 */
export function MarkdownMessage({ content, streaming = false }: { content: string; streaming?: boolean }) {
  const components = useMemo(() => markdownComponents(streaming), [streaming]);
  return (
    <div className={`markdown-body ${streaming ? "is-streaming" : ""}`} aria-busy={streaming}>
      <ReactMarkdown
        skipHtml
        remarkPlugins={[remarkGfm, remarkMath, remarkNoImages]}
        rehypePlugins={[[rehypeKatex, { throwOnError: false, strict: "ignore" }]]}
        components={components}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
