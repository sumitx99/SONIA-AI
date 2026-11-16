"use client";

import { useMemo } from "react";
import ReactMarkdown, { type Components, type ExtraProps } from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { MarkdownTable } from "@/components/chat/markdown-table";
import { MarkdownCode } from "@/components/chat/markdown-code";
import "katex/dist/katex.min.css";
import remarkNoImages from "@/lib/markdown/remark-no-images";
import remarkCitations from "@/lib/markdown/remark-citations";
import type { Citation } from "@/lib/api";
import { CitationMarker } from "@/components/chat/citation-marker";
import { GraphComponent } from "@/components/chat/graph-component";
import citationStyles from "./citation-marker.module.css";

/** A fenced code block's language tag (null when untagged) and raw text, or null for a non-code <pre>. */
function fencedBlock(node: ExtraProps["node"]): { language: string | null; source: string } | null {
  const code = node?.children[0];
  if (!code || code.type !== "element" || code.tagName !== "code") return null;
  const classes = code.properties?.className;
  const tag = Array.isArray(classes) ? classes.find((name) => String(name).startsWith("language-")) : undefined;
  return {
    language: tag === undefined ? null : String(tag).slice("language-".length),
    source: code.children.map((child) => (child.type === "text" ? child.value : "")).join(""),
  };
}

function markdownComponents(streaming: boolean, citations?: Citation[]): Components {
  return {
    // Only backend-verified attachments may render images. Model URLs can be invented,
    // expired or relative paths from a PDF, and otherwise produce broken duplicates.
    img: () => null,
    table: ({ node: _node, ...props }) => <MarkdownTable {...props} />,
    a: ({ node: _node, href, title, children, ...props }) => {
      if (title?.startsWith("sonia-grounding:") && href && /^https?:\/\//i.test(href)) {
        let sourceTitle = title.slice("sonia-grounding:".length);
        try { sourceTitle = decodeURIComponent(sourceTitle); } catch { /* keep the encoded label */ }
        return <sup><a href={href} className={citationStyles.groundingLink} target="_blank"
          rel="noreferrer nofollow" data-source-title={sourceTitle}
          aria-label={`Open grounding source: ${sourceTitle}`}>↗</a></sup>;
      }
      return <a {...props} href={href} title={title} target="_blank" rel="noreferrer nofollow">{children}</a>;
    },
    // A ```plotly block is a chart the model drew from the answer's numbers. The ```citations
    // block lists the sources behind the [n] markers; the server checks it and the markers show it.
    pre: ({ node, ...props }) => {
      const block = fencedBlock(node);
      if (block?.language === "citations") return null;
      if (block?.language === "plotly") return <GraphComponent source={block.source} streaming={streaming} />;
      return block ? <MarkdownCode {...props} {...block} /> : <pre {...props} />;
    },
    sup: ({ node: _node, ...props }) => {
      const n = Number((props as Record<string, unknown>)["data-citation"]);
      if (!n) return <sup {...props} />;
      return <CitationMarker n={n} citation={citations?.find((item) => item.n === n)} pending={streaming} />;
    },
  };
}

/**
 * Renders an answer written in GitHub-flavoured Markdown with $…$ / $$…$$ maths.
 * Raw HTML in the text is dropped, never rendered (model output is untrusted).
 * While `streaming`, a caret follows the last line of text. `citations` fill in the [n] markers.
 */
export function MarkdownMessage({ content, streaming = false, citations }: {
  content: string; streaming?: boolean; citations?: Citation[];
}) {
  const components = useMemo(() => markdownComponents(streaming, citations), [streaming, citations]);
  return (
    <div className={`markdown-body ${streaming ? "is-streaming" : ""}`} aria-busy={streaming}>
      <ReactMarkdown
        skipHtml
        remarkPlugins={[remarkGfm, remarkMath, remarkNoImages, remarkCitations]}
        rehypePlugins={[[rehypeKatex, { throwOnError: false, strict: "ignore" }]]}
        components={components}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
