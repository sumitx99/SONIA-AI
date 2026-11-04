type Node = { type: string; value?: string; children?: Node[]; data?: Record<string, unknown> };

const MARKER = /\[(\d{1,2})\]/g;
// Code, maths and link text keep a literal "[1]".
const SKIP = new Set(["code", "inlineCode", "math", "inlineMath", "link", "linkReference"]);

/** Turn citation markers like "[3]" in answer text into numbered superscripts the chat can open. */
export default function remarkCitations() {
  return function mark(node: Node) {
    if (!node.children || SKIP.has(node.type)) return;
    node.children = node.children.flatMap((child) => {
      if (child.type !== "text" || !child.value) {
        mark(child);
        return [child];
      }
      const parts: Node[] = [];
      let last = 0;
      for (const match of child.value.matchAll(MARKER)) {
        const start = match.index ?? 0;
        if (start > last) parts.push({ type: "text", value: child.value.slice(last, start) });
        parts.push({ type: "citation", children: [{ type: "text", value: match[1] }],
                     data: { hName: "sup", hProperties: { "data-citation": match[1] } } });
        last = start + match[0].length;
      }
      if (!parts.length) return [child];
      if (last < child.value.length) parts.push({ type: "text", value: child.value.slice(last) });
      return parts;
    });
  };
}
