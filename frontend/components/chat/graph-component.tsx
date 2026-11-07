"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { AlertTriangle, BarChart3, Check, Copy, Download, Loader2, Maximize2, Table2, X } from "lucide-react";
import { chartTables, parseChartSpec, type ChartBundle, type ChartSpec } from "@/lib/markdown/chart-spec";
import styles from "./graph-component.module.css";

// Each build is loaded only when an answer has a chart that needs it (1.3–2.8 MB each).
const PLOTLY_BUILDS: Record<ChartBundle, () => Promise<{ default: PlotlyApi }>> = {
  cartesian: () => import("plotly.js-cartesian-dist-min"),
  geo: () => import("plotly.js-geo-dist-min"),
  map: () => import("plotly.js-map-dist-min"),
};

const INK = "#292826";
const MUTED = "#77706b";
const GRID = "#ece6dc";
// Sonia's palette first; Plotly cycles through it for each series.
const COLORWAY = ["#c8553d", "#403f3d", "#5b7f95", "#d9a441", "#847971", "#4f6b3d", "#8a6fae", "#b5838d"];

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

function axis(overrides: unknown) {
  return { gridcolor: GRID, zerolinecolor: "#d8d0c4", linecolor: "#d8d0c4", automargin: true,
           ...(isObject(overrides) ? overrides : {}) };
}

/** The model's layout in Sonia's look. The title is shown on the card instead of in the plot. */
function themedLayout(spec: ChartSpec, font: string) {
  const { title: _title, xaxis, yaxis, geo, map, ...rest } = spec.layout;
  return {
    colorway: COLORWAY,
    ...rest,
    font: { family: font, size: 12, color: INK },
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    margin: { t: 12, r: 16, b: 16, l: 16 },
    // Hover text otherwise inherits the dark plot font and disappears on this background.
    hoverlabel: { font: { family: font, size: 12, color: "#ffffff" }, bgcolor: INK, bordercolor: INK },
    legend: { orientation: "h", x: 0, y: -0.18, font: { color: MUTED }, ...(isObject(rest.legend) ? rest.legend : {}) },
    xaxis: axis(xaxis),
    yaxis: axis(yaxis),
    ...(spec.bundle === "geo" && { geo: {
      bgcolor: "rgba(0,0,0,0)", landcolor: "#f1ebe1", showland: true, showcountries: true,
      countrycolor: "#cfc6b8", coastlinecolor: "#cfc6b8", showframe: false,
      projection: { type: "natural earth" }, ...(isObject(geo) ? geo : {}),
    } }),
    // The app picks the tile style; the model only says where to look.
    ...(spec.bundle === "map" && { map: { style: "carto-positron", zoom: 1, ...(isObject(map) ? map : {}) } }),
  };
}

function GraphPlot({ spec, height, onReady }: {
  spec: ChartSpec; height: number; onReady?: (draw: { element: HTMLDivElement; plotly: PlotlyApi } | null) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<"loading" | "ready" | "failed">("loading");

  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    let cancelled = false;
    let plotly: PlotlyApi | null = null;
    const observer = new ResizeObserver(() => plotly && plotly.Plots.resize(element));
    PLOTLY_BUILDS[spec.bundle]()
      .then(async (module) => {
        if (cancelled) return;
        plotly = module.default;
        const font = getComputedStyle(element).fontFamily;
        // Plotly writes into the objects it is given, so it gets copies. Points on maps are
        // drawn larger than Plotly's default so they stand out from the place names.
        const data = structuredClone(spec.data).map((trace) =>
          (trace.type === "scattermap" || trace.type === "scattergeo") && !isObject(trace.marker)
            ? { ...trace, marker: { size: 11 } } : trace);
        await plotly.react(element, data, themedLayout(structuredClone(spec), font), {
          responsive: true, displaylogo: false, scrollZoom: spec.bundle !== "cartesian",
          modeBarButtonsToRemove: ["select2d", "lasso2d", "toImage", "sendDataToCloud"],
        });
        if (cancelled) return;
        observer.observe(element);
        setState("ready");
        onReady?.({ element, plotly });
      })
      .catch(() => !cancelled && setState("failed"));
    return () => {
      cancelled = true;
      observer.disconnect();
      onReady?.(null);
      if (plotly) plotly.purge(element);
    };
  }, [spec, onReady]);

  return (
    <div className={styles.plotArea} style={{ height }}>
      <div ref={ref} className={styles.plot} aria-hidden={state !== "ready"} />
      {state === "loading" && <div className={styles.placeholder}><Loader2 size={16} className="animate-spin" /> Drawing chart…</div>}
      {state === "failed" && <div className={styles.placeholder}><AlertTriangle size={16} /> The chart couldn’t be drawn.</div>}
    </div>
  );
}

function DataTables({ spec }: { spec: ChartSpec }) {
  const tables = useMemo(() => chartTables(spec), [spec]);
  const [copied, setCopied] = useState(false);

  async function copyCsv() {
    const cell = (value: unknown) => {
      const text = String(value ?? "");
      return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
    };
    const csv = tables.map((table) => [table.columns, ...table.rows].map((row) => row.map(cell).join(",")).join("\n"))
      .join("\n\n");
    await navigator.clipboard.writeText(csv);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  }

  if (tables.length === 0) return <p className={styles.empty}>This chart has no table view.</p>;
  return (
    <div className={styles.data}>
      <button type="button" className={styles.copy} onClick={copyCsv}>
        {copied ? <Check size={13} /> : <Copy size={13} />} {copied ? "Copied" : "Copy as CSV"}
      </button>
      {tables.map((table) => (
        <div key={table.name} className={styles.tableScroll} tabIndex={0} role="region" aria-label={`${table.name} data`}>
          {tables.length > 1 && <p className={styles.tableName}>{table.name}</p>}
          <table>
            <thead><tr>{table.columns.map((column) => <th key={column}>{column}</th>)}</tr></thead>
            <tbody>
              {table.rows.map((row, index) => (
                <tr key={index}>{row.map((value, column) => <td key={column}>{String(value)}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}

const fileName = (title: string) =>
  title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60) || "sonia-chart";

/**
 * An interactive chart from a ```plotly block in an answer: hover for values, drag to zoom,
 * double-click to reset, a Data view with the numbers, PNG download and a larger view.
 * While the answer is still streaming the block is incomplete, so a placeholder shows instead.
 */
export function GraphComponent({ source, streaming = false }: { source: string; streaming?: boolean }) {
  const parsed = useMemo(() => parseChartSpec(source), [source]);
  const [view, setView] = useState<"chart" | "data">("chart");
  const [expanded, setExpanded] = useState(false);
  const plot = useRef<{ element: HTMLDivElement; plotly: PlotlyApi } | null>(null);
  const onReady = useMemo(() => (draw: typeof plot.current) => { plot.current = draw; }, []);

  if ("error" in parsed) {
    if (streaming) {
      return (
        <figure className={styles.card}>
          <div className={styles.placeholder} style={{ height: 120 }}><Loader2 size={16} className="animate-spin" /> Preparing chart…</div>
        </figure>
      );
    }
    return (
      <figure className={`${styles.card} ${styles.failed}`}>
        <p><AlertTriangle size={14} /> {parsed.error}</p>
        <details><summary>Show chart data</summary><pre>{source}</pre></details>
      </figure>
    );
  }

  const spec = parsed;
  const label = spec.bundle === "cartesian" ? "CHART" : "MAP";
  return (
    <figure className={styles.card} aria-label={spec.title || "Chart"}>
      <header className={styles.header}>
        <span className={styles.heading}>
          <span className="mono">{label}</span>
          {spec.title && <strong>{spec.title}</strong>}
        </span>
        <div className={styles.toggle} role="group" aria-label="Show as">
          <button type="button" aria-pressed={view === "chart"} onClick={() => setView("chart")}>
            <BarChart3 size={13} /> Chart
          </button>
          <button type="button" aria-pressed={view === "data"} onClick={() => setView("data")}>
            <Table2 size={13} /> Data
          </button>
        </div>
        <button type="button" className={styles.icon} aria-label="Download as PNG" title="Download as PNG"
          disabled={view !== "chart"}
          onClick={() => plot.current && plot.current.plotly.downloadImage(plot.current.element,
            { format: "png", filename: fileName(spec.title), scale: 2 })}>
          <Download size={15} />
        </button>
        <button type="button" className={styles.icon} aria-label="Open larger" title="Open larger"
          onClick={() => setExpanded(true)}>
          <Maximize2 size={15} />
        </button>
      </header>
      {view === "chart" ? <GraphPlot spec={spec} height={340} onReady={onReady} /> : <DataTables spec={spec} />}
      <figcaption className={styles.hint}>
        {spec.bundle === "cartesian" ? "Hover for values · drag to zoom · double-click to reset"
          : "Hover for values · scroll or drag to move · double-click to reset"}
      </figcaption>

      <Dialog.Root open={expanded} onOpenChange={setExpanded}>
        <Dialog.Portal>
          <Dialog.Overlay className={styles.overlay} />
          <Dialog.Content className={styles.dialog} aria-describedby={undefined}>
            <header className={styles.header}>
              <span className={styles.heading}>
                <span className="mono">{label}</span>
                <Dialog.Title asChild><strong>{spec.title || "Chart"}</strong></Dialog.Title>
              </span>
              <Dialog.Close className={styles.icon} aria-label="Close"><X size={16} /></Dialog.Close>
            </header>
            {expanded && <GraphPlot spec={spec} height={Math.round(window.innerHeight * 0.72)} />}
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </figure>
  );
}
