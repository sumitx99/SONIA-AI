import { z } from "zod";

// Mirrors the catalog in backend/app/services/genui.py. Saved history and stream snapshots
// are re-validated here, so a spec the backend no longer accepts is never rendered.
export const GENUI_LIMITS = {
  nodes: 48, depth: 8, stateKeys: 16, diagramNodes: 32, diagramEdges: 64, diagramGroups: 8,
  steps: 12, stepTargets: 12, points: 60, series: 6, parts: 8, sliderBound: 1000,
} as const;
export const NODE_KINDS = ["process", "data", "actor", "decision", "queue", "external"] as const;
export const TONES = ["neutral", "accent", "success", "warning", "danger"] as const;

const id = z.string().regex(/^[A-Za-z][A-Za-z0-9_-]{0,39}$/);
const boundedText = (max: number) => z.string().min(1).refine(text => [...text].length <= max);
const label = boundedText(100);
const number = z.number().finite().min(-1e12).max(1e12);
const value = z.union([z.boolean(), number, label]);
const integer = (min: number, max: number) => z.number().int().min(min).max(max);
const bound = integer(-GENUI_LIMITS.sliderBound, GENUI_LIMITS.sliderBound);

const base = z.object({
  id,
  parent: id.nullish(),
  visible_when: z.object({ key: id, equals: value }).strict().nullish(),
});
const layout = base.extend({ type: z.enum(["column", "row", "card"]), title: label.nullish() }).strict();
const text = base.extend({ type: z.literal("text"), content: boundedText(600), state_key: id.nullish() }).strict();
const button = base.extend({ type: z.literal("button"), label, key: id, value }).strict();
const slider = base.extend({
  type: z.literal("slider"), label, key: id, min: bound, max: bound, step: integer(1, 100).default(1),
}).strict();

const diagram = base.extend({
  type: z.literal("diagram"),
  title: label,
  direction: z.enum(["right", "down"]).default("right"),
  nodes: z.array(z.object({
    id, label: boundedText(60), detail: boundedText(80).nullish(),
    kind: z.enum(NODE_KINDS).default("process"), tone: z.enum(TONES).default("neutral"), group: id.nullish(),
  }).strict()).min(1).max(GENUI_LIMITS.diagramNodes),
  edges: z.array(z.object({
    id, source: id, target: id, label: boundedText(40).nullish(), dashed: z.boolean().default(false),
  }).strict()).max(GENUI_LIMITS.diagramEdges).default([]),
  groups: z.array(z.object({ id, label: boundedText(60) }).strict()).max(GENUI_LIMITS.diagramGroups).default([]),
  steps: z.array(z.object({
    caption: boundedText(200),
    focus: z.array(id).max(GENUI_LIMITS.stepTargets).default([]),
    flow: z.array(id).max(GENUI_LIMITS.stepTargets).default([]),
  }).strict()).max(GENUI_LIMITS.steps).default([]),
  build: z.boolean().default(false),
}).strict();

const chart = base.extend({
  type: z.literal("chart"), title: label, chart_type: z.enum(["bar", "line", "area", "pie"]),
  x_label: label, y_label: label, stacked: z.boolean().default(false),
  data: z.array(z.object({
    name: label, value: number, series: label.nullish(), citation: integer(1, 99).nullish(),
  }).strict()).min(1).max(GENUI_LIMITS.points),
  series_key: id.nullish(),
  count_key: id.nullish(),
}).strict();
const component = z.discriminatedUnion("type", [layout, text, button, slider, diagram, chart]);
const specSchema = z.object({
  version: z.literal("2.0"),
  initial_state: z.record(id, value),
  nodes: z.array(component).min(1).max(GENUI_LIMITS.nodes),
}).strict();

export type GenUISpec = z.infer<typeof specSchema>;
export type GenUINode = z.infer<typeof component>;
export type DiagramSpec = z.infer<typeof diagram>;
export type ChartSpec = z.infer<typeof chart>;

const tooMany = (list: unknown, max: number) => list !== undefined && (!Array.isArray(list) || list.length > max);

function validDiagram(node: DiagramSpec) {
  const nodes = new Set(node.nodes.map(item => item.id));
  const edges = new Set(node.edges.map(edge => edge.id));
  const groups = new Set(node.groups.map(group => group.id));
  // Edges have their own ID space (steps name them in `flow`); groups share the layout graph with nodes.
  return nodes.size === node.nodes.length && edges.size === node.edges.length && groups.size === node.groups.length
    && ![...groups].some(group => nodes.has(group))
    && node.edges.every(edge => nodes.has(edge.source) && nodes.has(edge.target) && edge.source !== edge.target)
    && node.nodes.every(item => item.group == null || groups.has(item.group))
    && node.steps.every(step => step.focus.length + step.flow.length > 0
      && step.focus.every(target => nodes.has(target)) && step.flow.every(target => edges.has(target)))
    && (!node.build || node.steps.length > 0);
}

function validChart(node: ChartSpec, state: Map<string, unknown>) {
  const series = new Set(node.data.map(point => point.series ?? null));
  const named = !series.has(null);
  if ((series.has(null) && series.size > 1) || series.size > GENUI_LIMITS.series) return false;
  if (new Set(node.data.map(point => JSON.stringify([point.series ?? null, point.name]))).size !== node.data.length) return false;
  if (node.chart_type === "pie" && (named || node.data.length > GENUI_LIMITS.parts || node.data.some(point => point.value < 0) || !node.data.some(point => point.value))) return false;
  if (node.stacked && (!named || (node.chart_type !== "bar" && node.chart_type !== "area"))) return false;
  if (node.series_key != null && (!named || typeof state.get(node.series_key) !== "string")) return false;
  return node.count_key == null || typeof state.get(node.count_key) === "number";
}

export function parseGenUI(input: unknown): GenUISpec | null {
  if (!input || typeof input !== "object") return null;
  // Check array sizes before Zod walks a potentially untrusted payload.
  const raw = input as { nodes?: unknown; initial_state?: unknown };
  if (!Array.isArray(raw.nodes) || raw.nodes.length > GENUI_LIMITS.nodes ||
      !raw.initial_state || typeof raw.initial_state !== "object" ||
      Object.keys(raw.initial_state).length > GENUI_LIMITS.stateKeys) return null;
  for (const node of raw.nodes) {
    if (!node || typeof node !== "object") return null;
    if (node.type === "chart" && tooMany(node.data, GENUI_LIMITS.points)) return null;
    if (node.type === "diagram" && (
      tooMany(node.nodes, GENUI_LIMITS.diagramNodes) || tooMany(node.edges, GENUI_LIMITS.diagramEdges) ||
      tooMany(node.groups, GENUI_LIMITS.diagramGroups) || tooMany(node.steps, GENUI_LIMITS.steps)
    )) return null;
  }
  const result = specSchema.safeParse(input);
  if (!result.success) return null;
  const spec = result.data;

  const sliderKeys = spec.nodes.flatMap(node => node.type === "slider" ? [node.key] : []);
  const sliders = new Set(sliderKeys);
  if (sliders.size !== sliderKeys.length) return null;
  const depths = new Map<string, number>();
  const ids = new Set<string>();
  const state = new Map(Object.entries(spec.initial_state));
  for (const [index, node] of spec.nodes.entries()) {
    const parentDepth = node.parent ? depths.get(node.parent) : (index === 0 ? 0 : undefined);
    if (ids.has(node.id) || parentDepth === undefined || parentDepth >= GENUI_LIMITS.depth) return null;
    ids.add(node.id);
    const condition = node.visible_when;
    if (condition && typeof state.get(condition.key) !== typeof condition.equals) return null;
    switch (node.type) {
      case "column":
      case "row":
      case "card":
        depths.set(node.id, parentDepth + 1);
        break;
      case "text":
        if (node.state_key && !state.has(node.state_key)) return null;
        break;
      case "button":
        if (sliders.has(node.key) || typeof state.get(node.key) !== typeof node.value) return null;
        break;
      case "slider": {
        const initial = state.get(node.key);
        if (typeof initial !== "number" || node.max <= node.min || (node.max - node.min) % node.step ||
            initial < node.min || initial > node.max || (initial - node.min) % node.step) return null;
        break;
      }
      case "diagram":
        if (!validDiagram(node)) return null;
        break;
      case "chart":
        if (!validChart(node, state)) return null;
        break;
    }
  }
  return spec;
}
