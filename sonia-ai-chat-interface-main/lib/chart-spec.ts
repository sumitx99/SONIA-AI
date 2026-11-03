/**
 * Charts in answers: the model writes a ```plotly block holding {"data": [...], "layout": {...}}
 * (a Plotly figure as JSON) and the chat draws it. The JSON is untrusted model output, so only
 * known trace types and layout settings pass, nothing may load from a URL the model chose, and
 * the amount of data is capped.
 */

export type ChartBundle = "cartesian" | "geo" | "map";
type Json = Record<string, unknown>;

export interface ChartSpec {
  data: Json[];
  layout: Json;
  /** Which Plotly build can draw it (smallest that has every trace type). */
  bundle: ChartBundle;
  title: string;
}

// Trace type -> the partial Plotly bundle that contains it ("scatter" is in all of them).
const TRACE_BUNDLES: Record<string, ChartBundle | "any"> = {
  scatter: "any",
  bar: "cartesian", pie: "cartesian", histogram: "cartesian", box: "cartesian",
  violin: "cartesian", heatmap: "cartesian", contour: "cartesian",
  choropleth: "geo", scattergeo: "geo",
  scattermap: "map", densitymap: "map",
};

// Layout settings a chart may set; everything else (images, menus, templates, tokens…) is dropped.
const LAYOUT_KEYS = new Set([
  "title", "xaxis", "yaxis", "xaxis2", "yaxis2", "legend", "showlegend", "barmode", "barnorm",
  "boxmode", "violinmode", "bargap", "hovermode", "annotations", "shapes", "grid", "geo", "map",
  "coloraxis", "colorway",
]);
const GEO_KEYS = new Set([
  "scope", "projection", "center", "fitbounds", "resolution", "showcountries", "showland",
  "showocean", "showlakes", "showrivers", "showcoastlines", "showframe", "lataxis", "lonaxis",
]);
const ARRAY_KEYS = ["x", "y", "z", "values", "labels", "lat", "lon", "locations", "text"];
export const MAX_TRACES = 20;
export const MAX_POINTS = 20_000;

const isObject = (value: unknown): value is Json =>
  typeof value === "object" && value !== null && !Array.isArray(value);

/** Text of a Plotly title, which may be a string or {"text": …}. */
export function titleText(title: unknown): string {
  if (typeof title === "string") return title;
  return isObject(title) && typeof title.text === "string" ? title.text : "";
}

function pointsIn(trace: Json): number {
  return Math.max(0, ...ARRAY_KEYS.map((key) => {
    const value = trace[key];
    if (!Array.isArray(value)) return 0;
    // A heatmap's z is rows of columns.
    return value.reduce<number>((sum, item) => sum + (Array.isArray(item) ? item.length : 1), 0);
  }));
}

function cleanTrace(trace: Json): Json {
  // geojson may be a URL the browser would fetch; maps outline places from Plotly's own data.
  const { geojson: _geojson, transforms: _transforms, ...rest } = trace;
  return rest;
}

function cleanLayout(layout: Json): Json {
  const clean: Json = {};
  for (const [key, value] of Object.entries(layout)) {
    if (!LAYOUT_KEYS.has(key)) continue;
    if (key === "geo" && isObject(value)) {
      clean.geo = Object.fromEntries(Object.entries(value).filter(([geoKey]) => GEO_KEYS.has(geoKey)));
    } else if (key === "map" && isObject(value)) {
      // Only where to look: the map style (which loads tiles and fonts) is chosen by the app.
      const { center, zoom } = value;
      clean.map = { ...(isObject(center) && { center }), ...(typeof zoom === "number" && { zoom }) };
    } else if (key === "shapes" && Array.isArray(value)) {
      clean.shapes = value.filter((shape) => isObject(shape) && shape.type !== "path").slice(0, 50);
    } else if (key === "annotations" && Array.isArray(value)) {
      clean.annotations = value.slice(0, 50);
    } else {
      clean[key] = value;
    }
  }
  return clean;
}

/** Reads a ```plotly block; returns an error message for anything that can't be drawn safely. */
export function parseChartSpec(source: string): ChartSpec | { error: string } {
  let figure: unknown;
  try {
    figure = JSON.parse(source);
  } catch {
    return { error: "The chart data is incomplete or not valid JSON." };
  }
  if (!isObject(figure) || !Array.isArray(figure.data) || figure.data.length === 0)
    return { error: "The chart has no data." };
  if (figure.data.length > MAX_TRACES) return { error: `Charts can have at most ${MAX_TRACES} series.` };

  const bundles = new Set<ChartBundle>();
  const data: Json[] = [];
  let points = 0;
  for (const trace of figure.data) {
    if (!isObject(trace)) return { error: "The chart data is malformed." };
    const type = typeof trace.type === "string" ? trace.type : "scatter";
    const bundle = TRACE_BUNDLES[type];
    if (!bundle) return { error: `“${type}” charts aren't supported.` };
    if (bundle !== "any") bundles.add(bundle);
    points += pointsIn(trace);
    data.push({ ...cleanTrace(trace), type });
  }
  if (points > MAX_POINTS) return { error: "The chart has too many points to draw." };
  if (bundles.size > 1) return { error: "A chart can't mix map and non-map series." };

  const layout = cleanLayout(isObject(figure.layout) ? figure.layout : {});
  return { data, layout, bundle: [...bundles][0] ?? "cartesian", title: titleText(layout.title) };
}

/** One table per series, for the chart's "Data" view and copying. */
export function chartTables(spec: ChartSpec): { name: string; columns: string[]; rows: unknown[][] }[] {
  return spec.data.flatMap((trace, index) => {
    // 1-D columns only: a heatmap's z grid doesn't fit a list of rows.
    const columns = ARRAY_KEYS.filter((key) => Array.isArray(trace[key]) && !(trace[key] as unknown[]).some(Array.isArray));
    if (columns.length === 0) return [];
    const length = Math.max(...columns.map((key) => (trace[key] as unknown[]).length));
    const rows = Array.from({ length }, (_, row) => columns.map((key) => (trace[key] as unknown[])[row] ?? ""));
    const name = typeof trace.name === "string" && trace.name ? trace.name : `Series ${index + 1}`;
    return [{ name, columns, rows }];
  });
}
