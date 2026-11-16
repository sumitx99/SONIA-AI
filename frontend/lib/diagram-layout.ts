import dagre from "@dagrejs/dagre";
import type { DiagramSpec } from "@/lib/genui";

/** Every size the diagram is drawn with, in SVG user units. The renderer reads the same values. */
export const DIAGRAM_METRICS = {
  labelSize: 13,
  labelWeight: 600,
  detailSize: 11.5,
  detailWeight: 400,
  edgeLabelSize: 11.5,
  edgeLabelWeight: 500,
  lineHeight: 1.35,
  maxTextWidth: 176,
  minNodeWidth: 104,
  paddingX: 16,
  paddingY: 12,
  detailGap: 3,
  nodeGap: 32,
  rankGap: 68,
  margin: 14,
  cornerRadius: 10,
  edgeLabelPadX: 6,
  edgeLabelPadY: 3,
  groupPadding: 18,
  groupLabelHeight: 22,
  cylinderCap: 7,
  queueSlot: 6,
  queueSlots: 2,
  // A diagram wider than its container shrinks to this share of its natural size, then scrolls.
  minScale: 0.72,
} as const;

type Kind = DiagramSpec["nodes"][number]["kind"];
type TextRole = "label" | "detail" | "edgeLabel";
export type Measure = (text: string, role: TextRole) => number;

/** Space a shape needs around its text beyond the shared padding, as [left, top, right, bottom]. */
function shapeInset(kind: Kind, textWidth: number, textHeight: number): [number, number, number, number] {
  const m = DIAGRAM_METRICS;
  switch (kind) {
    case "data": return [0, m.cylinderCap * 2, 0, m.cylinderCap];
    case "queue": return [0, 0, m.queueSlot * (m.queueSlots + 1), 0];
    case "actor": return [textHeight / 2, 0, textHeight / 2, 0];
    // A diamond holds a rectangle of half its width and height.
    case "decision": return [textWidth / 2, textHeight / 2, textWidth / 2, textHeight / 2];
    default: return [0, 0, 0, 0];
  }
}

function wrap(text: string, role: TextRole, measure: Measure): string[] {
  const limit = DIAGRAM_METRICS.maxTextWidth;
  const lines: string[] = [];
  let line = "";
  for (const word of text.split(/\s+/).filter(Boolean)) {
    const candidate = line ? `${line} ${word}` : word;
    if (measure(candidate, role) <= limit) {
      line = candidate;
      continue;
    }
    if (line) lines.push(line);
    line = "";
    // A single word wider than the box breaks wherever it stops fitting.
    for (const character of word) {
      if (line && measure(line + character, role) > limit) {
        lines.push(line);
        line = "";
      }
      line += character;
    }
  }
  if (line) lines.push(line);
  return lines;
}

export interface PlacedNode {
  id: string; kind: Kind; tone: DiagramSpec["nodes"][number]["tone"];
  x: number; y: number; width: number; height: number;
  /** Centre of the text block and the baseline offsets of its lines from that centre. */
  textX: number; textY: number; lines: string[]; detail: string[]; title: string;
}
export interface PlacedEdge {
  id: string; source: string; target: string; path: string; dashed: boolean;
  label?: { text: string; x: number; y: number; width: number; height: number };
}
export interface PlacedGroup { id: string; label: string; x: number; y: number; width: number; height: number }
export interface DiagramLayout {
  width: number; height: number; nodes: PlacedNode[]; edges: PlacedEdge[]; groups: PlacedGroup[];
}

type Point = { x: number; y: number };

/** Where the line from a node's centre toward `toward` leaves the node's outline. */
function boundary(node: PlacedNode, toward: Point): Point {
  const centre = { x: node.x + node.width / 2, y: node.y + node.height / 2 };
  const dx = toward.x - centre.x;
  const dy = toward.y - centre.y;
  if (!dx && !dy) return centre;
  const halfWidth = node.width / 2;
  const halfHeight = node.height / 2;
  const scale = node.kind === "decision"
    ? 1 / (Math.abs(dx) / halfWidth + Math.abs(dy) / halfHeight)
    : Math.min(dx ? halfWidth / Math.abs(dx) : Infinity, dy ? halfHeight / Math.abs(dy) : Infinity);
  return { x: centre.x + dx * scale, y: centre.y + dy * scale };
}

/** A smooth curve through the router's waypoints. */
function curve(points: Point[]): string {
  const [first, ...rest] = points;
  if (rest.length < 2) return `M${first.x},${first.y}` + rest.map(point => `L${point.x},${point.y}`).join("");
  let path = `M${first.x},${first.y}`;
  for (let index = 0; index < rest.length - 1; index++) {
    const control = rest[index];
    const next = rest[index + 1];
    const end = index === rest.length - 2 ? next : { x: (control.x + next.x) / 2, y: (control.y + next.y) / 2 };
    path += `Q${control.x},${control.y} ${end.x},${end.y}`;
  }
  return path;
}

const round = (value: number) => Math.round(value * 10) / 10;

export function layoutDiagram(spec: DiagramSpec, measure: Measure): DiagramLayout {
  const m = DIAGRAM_METRICS;
  const graph = new dagre.graphlib.Graph({ compound: true, multigraph: true });
  graph.setGraph({
    rankdir: spec.direction === "down" ? "TB" : "LR",
    nodesep: m.nodeGap, ranksep: m.rankGap, marginx: m.margin, marginy: m.margin + m.groupLabelHeight,
  });
  graph.setDefaultEdgeLabel(() => ({}));

  const labelLine = m.labelSize * m.lineHeight;
  const detailLine = m.detailSize * m.lineHeight;
  const text = new Map(spec.nodes.map(node => {
    const lines = wrap(node.label, "label", measure);
    const detail = node.detail ? wrap(node.detail, "detail", measure) : [];
    const width = Math.max(...lines.map(line => measure(line, "label")), ...detail.map(line => measure(line, "detail")));
    const height = lines.length * labelLine + (detail.length ? m.detailGap + detail.length * detailLine : 0);
    return [node.id, { lines, detail, width, height, inset: shapeInset(node.kind, width, height) }];
  }));

  for (const group of spec.groups) graph.setNode(group.id, { clusterLabelPos: "top", paddingTop: m.groupPadding });
  for (const node of spec.nodes) {
    const block = text.get(node.id)!;
    const [left, top, right, bottom] = block.inset;
    graph.setNode(node.id, {
      width: Math.max(m.minNodeWidth, block.width + m.paddingX * 2 + left + right),
      height: block.height + m.paddingY * 2 + top + bottom,
    });
    if (node.group) graph.setParent(node.id, node.group);
  }
  for (const edge of spec.edges) {
    graph.setEdge(edge.source, edge.target, edge.label ? {
      width: measure(edge.label, "edgeLabel") + m.edgeLabelPadX * 2,
      height: m.edgeLabelSize * m.lineHeight + m.edgeLabelPadY * 2,
      labelpos: "c",
    } : {}, edge.id);
  }
  dagre.layout(graph);

  const nodes = spec.nodes.map(node => {
    const placed = graph.node(node.id) as { x: number; y: number; width: number; height: number };
    const block = text.get(node.id)!;
    const [left, top, right, bottom] = block.inset;
    const x = placed.x - placed.width / 2;
    const y = placed.y - placed.height / 2;
    return {
      id: node.id, kind: node.kind, tone: node.tone, title: node.label,
      x: round(x), y: round(y), width: round(placed.width), height: round(placed.height),
      textX: round(x + (placed.width + left - right) / 2),
      textY: round(y + (placed.height + top - bottom) / 2 - block.height / 2),
      lines: block.lines, detail: block.detail,
    };
  });
  const byId = new Map(nodes.map(node => [node.id, node]));

  const edges = spec.edges.map(edge => {
    const routed = graph.edge({ v: edge.source, w: edge.target, name: edge.id }) as
      { points: Point[]; x?: number; y?: number; width?: number; height?: number };
    const inner = routed.points.slice(1, -1);
    const source = byId.get(edge.source)!;
    const target = byId.get(edge.target)!;
    const centre = (node: PlacedNode) => ({ x: node.x + node.width / 2, y: node.y + node.height / 2 });
    const points = [
      boundary(source, inner[0] ?? centre(target)), ...inner,
      boundary(target, inner[inner.length - 1] ?? centre(source)),
    ].map(point => ({ x: round(point.x), y: round(point.y) }));
    return {
      id: edge.id, source: edge.source, target: edge.target, dashed: edge.dashed, path: curve(points),
      ...(edge.label && routed.x !== undefined && routed.y !== undefined && {
        label: { text: edge.label, x: round(routed.x), y: round(routed.y), width: round(routed.width!), height: round(routed.height!) },
      }),
    };
  });

  const groups = spec.groups.flatMap(group => {
    if (!spec.nodes.some(node => node.group === group.id)) return [];
    const box = graph.node(group.id) as { x: number; y: number; width: number; height: number };
    // The label sits in a band above the members, inside the group's outline.
    return [{
      id: group.id, label: group.label, x: round(box.x - box.width / 2),
      y: round(box.y - box.height / 2 - m.groupLabelHeight),
      width: round(box.width), height: round(box.height + m.groupLabelHeight),
    }];
  });

  const size = graph.graph() as { width?: number; height?: number };
  return { width: Math.ceil(size.width ?? 0), height: Math.ceil(size.height ?? 0), nodes, edges, groups };
}
