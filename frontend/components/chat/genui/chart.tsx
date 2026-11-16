"use client";

import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { CitationMarker } from "@/components/chat/citation-marker";
import type { Citation } from "@/lib/api";
import { GENUI_LIMITS, type ChartSpec, type GenUISpec } from "@/lib/genui";
import styles from "./genui.module.css";

/** Mark sizes shared by every chart type. Colours and plot size live in the stylesheet. */
const MARKS = {
  barMaxWidth: 24,
  barRadius: 4,
  lineWidth: 2,
  dotRadius: 4,
  surfaceGap: 2,
  areaOpacity: 0.12,
  donutInner: "56%",
  donutOuter: "86%",
  tickSize: 11,
} as const;
const SURFACE = "var(--card)";
// A colour belongs to a series or part for good: filtering never repaints the ones that remain.
const colour = (index: number) => `var(--genui-series-${index + 1})`;
const compact = new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 });
const full = new Intl.NumberFormat(undefined, { maximumFractionDigits: 6 });
const tick = { fill: "var(--muted-foreground)", fontSize: MARKS.tickSize };
const key = (index: number) => `series${index}`;
const legendText = (value: string) => <span className={styles.legend}>{value}</span>;

export function Chart({ spec, state, citations, reducedMotion }: {
  spec: ChartSpec; state: GenUISpec["initial_state"]; citations?: Citation[]; reducedMotion: boolean;
}) {
  const verified = new Map(citations?.filter(item => item.verified).map(item => [item.n, item]));
  if (spec.data.some(point => point.citation != null && !verified.has(point.citation))) return null;

  const single = spec.data[0].series == null;
  const allSeries = single ? [spec.y_label] : [...new Set(spec.data.map(point => point.series!))];
  const allCategories = [...new Set(spec.data.map(point => point.name))];
  const cell = (category: string, series: string) =>
    spec.data.find(point => point.name === category && (single || point.series === series));

  const selected = spec.series_key ? state[spec.series_key] : undefined;
  const series = allSeries.filter(name => !allSeries.includes(selected as string) || name === selected);
  const count = spec.count_key ? Number(state[spec.count_key]) : allCategories.length;
  const categories = allCategories.slice(0, Math.max(1, Math.min(allCategories.length, Math.round(count))));
  const rows = categories.map(category => ({
    name: category, ...Object.fromEntries(series.map(name => [key(allSeries.indexOf(name)), cell(category, name)?.value])),
  }));

  const animate = !reducedMotion;
  const tooltip = <Tooltip formatter={(value: number) => full.format(value)}
    cursor={spec.chart_type === "bar" ? { fill: "var(--border)", fillOpacity: 0.4 } : { stroke: "var(--border)" }}
    contentStyle={{ background: SURFACE, borderColor: "var(--border)", borderRadius: 8, fontSize: 12 }}
    labelStyle={{ color: "var(--foreground)", fontWeight: 600 }} itemStyle={{ color: "var(--foreground)" }} />;
  const legend = <Legend iconType="circle" iconSize={8} formatter={legendText} />;
  const frame = <>
    <CartesianGrid vertical={false} stroke="var(--border)" />
    <XAxis dataKey="name" tick={tick} tickLine={false} axisLine={{ stroke: "var(--border)" }} />
    <YAxis tick={tick} tickLine={false} axisLine={false} width={44} tickFormatter={(value: number) => compact.format(value)} />
    {tooltip}
    {!single && legend}
  </>;
  const margin = { top: 12, right: 12, bottom: 4, left: 0 };
  const stack = spec.stacked ? "stack" : undefined;

  let plot: React.ReactElement;
  if (spec.chart_type === "pie") {
    const parts = allCategories.slice(0, GENUI_LIMITS.parts);
    plot = <PieChart>
      <Pie data={rows} dataKey={key(0)} name={spec.y_label} nameKey="name" innerRadius={MARKS.donutInner} outerRadius={MARKS.donutOuter}
        stroke={SURFACE} strokeWidth={MARKS.surfaceGap} isAnimationActive={animate}>
        {rows.map(row => <Cell key={row.name} fill={colour(parts.indexOf(row.name))} />)}
      </Pie>
      {tooltip}
      {legend}
    </PieChart>;
  } else if (spec.chart_type === "bar") {
    plot = <BarChart data={rows} margin={margin}>
      {frame}
      {series.map(name => <Bar key={name} dataKey={key(allSeries.indexOf(name))} name={name} stackId={stack} fill={colour(allSeries.indexOf(name))}
        maxBarSize={MARKS.barMaxWidth} radius={stack ? 0 : [MARKS.barRadius, MARKS.barRadius, 0, 0]}
        stroke={stack ? SURFACE : undefined} strokeWidth={stack ? MARKS.surfaceGap : undefined} isAnimationActive={animate} />)}
    </BarChart>;
  } else if (spec.chart_type === "area") {
    plot = <AreaChart data={rows} margin={margin}>
      {frame}
      {series.map(name => <Area key={name} dataKey={key(allSeries.indexOf(name))} name={name} stackId={stack} type="monotone"
        stroke={colour(allSeries.indexOf(name))} strokeWidth={MARKS.lineWidth}
        fill={colour(allSeries.indexOf(name))} fillOpacity={MARKS.areaOpacity} isAnimationActive={animate} />)}
    </AreaChart>;
  } else {
    plot = <LineChart data={rows} margin={margin}>
      {frame}
      {series.map(name => <Line key={name} dataKey={key(allSeries.indexOf(name))} name={name} type="monotone" stroke={colour(allSeries.indexOf(name))}
        strokeWidth={MARKS.lineWidth} strokeLinecap="round" strokeLinejoin="round"
        dot={{ r: MARKS.dotRadius, fill: colour(allSeries.indexOf(name)), stroke: SURFACE, strokeWidth: MARKS.surfaceGap }}
        activeDot={{ r: MARKS.dotRadius + 1, stroke: SURFACE, strokeWidth: MARKS.surfaceGap }} isAnimationActive={animate} />)}
    </LineChart>;
  }

  return <figure className={styles.figure}>
    <figcaption className={styles.title}>{spec.title}</figcaption>
    <div className={styles.chart} aria-hidden="true">
      {spec.chart_type !== "pie" && <div className={styles.axisLabel}>{spec.y_label}</div>}
      <div className={styles.plot}><ResponsiveContainer width="100%" height="100%">{plot}</ResponsiveContainer></div>
      {spec.chart_type !== "pie" && <div className={styles.axisLabel}>{spec.x_label}</div>}
    </div>
    <details className={styles.data}>
      <summary>View chart data</summary>
      <table aria-label={spec.title}>
        <thead><tr>
          <th scope="col">{spec.x_label}</th>
          {allSeries.map(name => <th key={name} scope="col">{name}</th>)}
        </tr></thead>
        <tbody>{allCategories.map(category => <tr key={category}>
          <th scope="row">{category}</th>
          {allSeries.map(name => {
            const point = cell(category, name);
            return <td key={name}>{point && <>
              {full.format(point.value)}
              {point.citation != null && <CitationMarker n={point.citation} citation={verified.get(point.citation)} pending={false} />}
            </>}</td>;
          })}
        </tr>)}</tbody>
      </table>
    </details>
  </figure>;
}
