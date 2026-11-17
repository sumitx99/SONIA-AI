"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import Image from "next/image";
import { useInView, useReducedMotion } from "motion/react";
import { ArrowUpRight, ChartNoAxesCombined, Check, ChevronLeft, ChevronRight, FileText, Globe, ImageIcon, Pause, Play, Plug, RotateCcw, Table2, Workflow } from "lucide-react";
import { Emblem } from "@/components/brand";
import { MarkdownTable } from "@/components/chat/markdown-table";
import documentImageStyles from "@/components/chat/document-image.module.css";
import { useLandingAnimation } from "./landing-motion";

const scenes = [
  { id: "graphs", label: "Graphs", icon: ChartNoAxesCombined, prompt: "Compare revenue and costs by quarter from this report.", title: "Revenue pulled ahead.", copy: "Both grew, but revenue rose faster every quarter. Switch between the series to compare them.", activity: "Reading quarterly figures…", source: "Quarterly report.pdf · p. 4", excerpt: "Revenue (USD thousands): Q1 24, Q2 38, Q3 46, Q4 64. Costs: Q1 20, Q2 26, Q3 31, Q4 35." },
  { id: "diagrams", label: "Diagrams", icon: Workflow, prompt: "Walk me through how a page request reaches the database.", title: "Follow the request, step by step.", copy: "The CDN answers first; only a cache miss reaches the app server, which reads the database.", activity: "Laying out the walkthrough…", source: "Architecture notes.pdf · p. 3", excerpt: "Requests reach the CDN first. On a cache miss the CDN forwards them to the app server, which reads the database." },
  { id: "tables", label: "Tables", icon: Table2, prompt: "Compare these three plans in a table.", title: "The details, side by side.", copy: "A clear comparison you can copy into your spreadsheet or document.", activity: "Comparing the plan details…", source: "Product plans.pdf · p. 2", excerpt: "Starter: Personal projects, 5 GB. Team: Working together, 50 GB. Business: Growing teams, 250 GB." },
  { id: "web", label: "Web search", icon: Globe, prompt: "Explore how attention shapes creative thinking.", title: "Make room for a better idea.", copy: "Focused attention gives ideas time to develop. Explore the findings, images, and sources together.", activity: "Searching and reading sources…", source: "Web research · illustrative sources and imagery", excerpt: "Focused attention gives ideas time to develop; reflection creates space to connect ideas." },
  { id: "mcp", label: "MCP tools", icon: Plug, prompt: "Find my project notes using connected tools.", title: "Your tools, in the conversation.", copy: "A connected MCP server finds your notes. Actions that make changes ask you first.", activity: "Calling connected notes tool…", source: "Project notes · connected MCP server", excerpt: "Launch checklist: Design review, milestones, and next steps." },
  { id: "pdf", label: "PDF images", icon: ImageIcon, prompt: "Show the creative process figure from this PDF.", title: "The figure, alongside the explanation.", copy: "The process moves from observation to reflection, then connection. Here’s the original figure from the page.", activity: "Finding the figure in your PDF…", source: "The creative process.pdf · p. 6 · Image 1", excerpt: "Figure 1. The creative process: Observe → Reflect → Connect." },
] as const;
type SceneId = (typeof scenes)[number]["id"];

// Illustrative series for the Graphs scene (USD thousands), matching its source excerpt.
const series = [
  { name: "Revenue", values: [24, 38, 46, 64] },
  { name: "Costs", values: [20, 26, 31, 35] },
];
const chart = { left: 30, right: 456, top: 12, bottom: 104, max: 70, ticks: [0, 35, 70] };
const chartX = (index: number) => chart.left + index * (chart.right - chart.left) / 3;
const chartY = (value: number) => chart.bottom - value / chart.max * (chart.bottom - chart.top);

function ChartScene() {
  const [shown, setShown] = useState<string>("All");
  const visible = series.map((item, index) => ({ ...item, index })).filter((item) => shown === "All" || item.name === shown);
  return <div className="demo-chart demo-genui-chart">
    <div className="demo-output-heading"><span>REVENUE VS COSTS / USD THOUSANDS</span><span>2026</span></div>
    <div className="demo-genui-controls">
      <div className="demo-genui-toggle" role="group" aria-label="Series shown">
        {["All", ...series.map((item) => item.name)].map((name) => <button key={name} type="button" aria-pressed={shown === name} onClick={() => setShown(name)}>{name}</button>)}
      </div>
      <div className="demo-genui-legend" aria-hidden="true">{series.map((item, index) => <span key={item.name}><i data-series={index} />{item.name}</span>)}</div>
    </div>
    <svg viewBox="0 0 480 122" role="img" aria-label="Illustrative revenue 24, 38, 46, 64 and costs 20, 26, 31, 35 thousand dollars, Q1 to Q4">
      {chart.ticks.map((tick) => <g key={tick}><path d={`M${chart.left} ${chartY(tick)} H${chart.right}`} className="demo-grid-line" /><text x={chart.left - 8} y={chartY(tick) + 3} textAnchor="end">{tick}</text></g>)}
      {visible.map((item) => {
        const points = item.values.map((value, index) => `${chartX(index)} ${chartY(value)}`);
        return <g key={item.name} data-series={item.index}>
          {item.index === 0 && <path d={`M${points.join(" L")} L${chart.right} ${chart.bottom} L${chart.left} ${chart.bottom}Z`} className="demo-genui-area" />}
          <path d={`M${points.join(" L")}`} pathLength="1" className="demo-chart-line demo-genui-line" />
          {item.values.map((value, index) => <circle key={index} cx={chartX(index)} cy={chartY(value)} r="4" />)}
        </g>;
      })}
      {["Q1", "Q2", "Q3", "Q4"].map((q, i) => <text key={q} x={chartX(i)} y="119" textAnchor="middle">{q}</text>)}
    </svg>
  </div>;
}

// The walkthrough plays three steps once the answer is ready; CSS times each step (see landing.css).
const walkthrough = [
  "The reader asks the nearest CDN node for the page.",
  "Only on a cache miss does the request reach the app server.",
  "The app server reads the content from the database.",
];

function DiagramScene() {
  return <div className="demo-chart demo-genui-diagram">
    <div className="demo-output-heading"><span>HOW A PAGE LOADS</span>
      <span className="demo-genui-steps" aria-hidden="true"><ChevronLeft size={11} /><Play size={10} /><ChevronRight size={11} />
        <span className="demo-genui-count">{walkthrough.map((_, index) => <span key={index} data-step={index + 1}>{index + 1} / {walkthrough.length}</span>)}</span>
      </span>
    </div>
    <svg viewBox="0 0 480 116" role="img" aria-label="Illustrative walkthrough: Reader to CDN over HTTPS, CDN to app server on a cache miss, app server to database">
      <defs><marker id="demo-flow-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 1L10 5L0 9Z" /></marker></defs>
      <g className="demo-genui-group"><rect x="98" y="6" width="126" height="104" rx="8" /><text x="108" y="20">Edge</text></g>
      <g className="demo-genui-group"><rect x="262" y="6" width="212" height="104" rx="8" /><text x="272" y="20">Origin</text></g>
      <g className="demo-genui-edge" data-step="1"><path d="M72 63 H108" markerEnd="url(#demo-flow-arrow)" /><rect x="76" y="45" width="30" height="13" rx="6.5" /><text x="91" y="55" textAnchor="middle">HTTPS</text></g>
      <g className="demo-genui-edge" data-step="2" data-dashed=""><path d="M212 63 H276" markerEnd="url(#demo-flow-arrow)" /><rect x="220" y="45" width="50" height="13" rx="6.5" /><text x="245" y="55" textAnchor="middle">cache miss</text></g>
      <g className="demo-genui-edge" data-step="3"><path d="M358 63 H382" markerEnd="url(#demo-flow-arrow)" /></g>
      <g className="demo-genui-node" data-step="1"><rect x="6" y="48" width="66" height="30" rx="15" /><text x="39" y="67" textAnchor="middle">Reader</text></g>
      <g className="demo-genui-node" data-step="1 2" data-kind="external"><rect x="110" y="38" width="102" height="50" rx="8" /><text x="161" y="60" textAnchor="middle">CDN</text><text x="161" y="75" textAnchor="middle" className="demo-genui-detail">Serves cached pages</text></g>
      <g className="demo-genui-node" data-step="2 3"><rect x="278" y="48" width="80" height="30" rx="8" /><text x="318" y="67" textAnchor="middle">App server</text></g>
      <g className="demo-genui-node" data-step="3"><path d="M384 46 a41 7 0 0 1 82 0 V80 a41 7 0 0 1 -82 0 Z" /><path className="demo-genui-inner" d="M384 46 a41 7 0 0 0 82 0" /><text x="425" y="70" textAnchor="middle">Database</text></g>
    </svg>
    <div className="demo-genui-caption">{walkthrough.map((caption, index) => <p key={index} data-step={index + 1}>{caption}</p>)}</div>
  </div>;
}

const duration = 9000;

function DemoOutput({ scene }: { scene: SceneId }) {
  if (scene === "graphs") return <ChartScene />;
  if (scene === "diagrams") return <DiagramScene />;
  if (scene === "tables") return <div className="demo-table-wrap markdown-body"><MarkdownTable>
    <caption className="sr-only">Illustrative plan comparison</caption>
    <thead><tr><th>Plan</th><th>For</th><th>Storage</th></tr></thead>
    <tbody>{[["Starter", "Personal projects", "5 GB"], ["Team", "Working together", "50 GB"], ["Business", "Growing teams", "250 GB"]].map((row) => <tr key={row[0]}>{row.map((cell) => <td key={cell}>{cell}</td>)}</tr>)}</tbody>
  </MarkdownTable></div>;
  if (scene === "web") return <div className="demo-research">
    <div className="demo-research-status"><Globe size={13} /><span>Web search complete</span><Check size={13} /></div>
    <div className="demo-research-result">
      <figure className="demo-research-image"><Image src="/images/sonia-marble-mind.png" alt="Illustrative marble sculpture representing creative thought" fill sizes="(max-width: 640px) 100px, 140px" /><figcaption>Visual inspiration</figcaption></figure>
      <div className="demo-research-summary"><span className="demo-output-heading">EXPLORE THE FINDINGS</span><strong>Attention & creative thinking</strong><span>Time to reflect. Space to connect ideas.</span><div className="demo-source-chips"><span>Research <ArrowUpRight size={10} /></span><span>Further reading <ArrowUpRight size={10} /></span></div></div>
    </div>
  </div>;
  if (scene === "pdf") return <figure className={`demo-pdf-figure ${documentImageStyles.figure}`}>
    <div className={documentImageStyles.mat}>
      <svg className="demo-pdf-image" viewBox="0 0 480 106" role="img" aria-label="Sample PDF figure: Observe, Reflect, Connect">
        <defs><marker id="demo-process-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M0 0L10 5L0 10" fill="#7c8969" /></marker></defs>
        <text x="20" y="17" className="demo-pdf-heading">FIG. 1 / THE CREATIVE PROCESS</text>
        {["Observe", "Reflect", "Connect"].map((label, index) => <g key={label}><rect x={20 + index * 160} y="37" width="120" height="46" rx="5" fill="#f1f2eb" stroke="#d9dece" /><text x={80 + index * 160} y="65" textAnchor="middle">{label}</text>{index < 2 && <path d={`M${145 + index * 160} 60h30`} stroke="#7c8969" markerEnd="url(#demo-process-arrow)" />}</g>)}
      </svg>
    </div>
    <figcaption className={documentImageStyles.caption}><strong>Page 6 · Image 1</strong><span className={documentImageStyles.heading}>The creative process · sample PDF figure</span></figcaption>
  </figure>;
  return <div className="demo-mcp">
    <div className="demo-mcp-tool"><Plug size={18} /><span><strong>Project notes</strong><small>MCP · Search notes</small></span><span className="demo-tool-done"><Check size={13} /> Done</span></div>
    <div className="demo-note"><FileText size={16} /><span><strong>Launch checklist</strong><small>Design review, milestones, and next steps.</small></span></div>
    <p className="demo-permission">Read-only tool · no approval needed</p>
  </div>;
}

export function FeaturePreview() {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { amount: 0.3 });
  const { active } = useLandingAnimation();
  const reduced = useReducedMotion();
  const [scene, setScene] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const [paused, setPaused] = useState(false);
  const [visible, setVisible] = useState(true);
  useEffect(() => {
    const update = () => setVisible(!document.hidden);
    update();
    document.addEventListener("visibilitychange", update);
    return () => document.removeEventListener("visibilitychange", update);
  }, []);
  useEffect(() => {
    if (!active || !inView || !visible || paused || reduced) return;
    const started = performance.now();
    const timer = window.setTimeout(() => {
      const next = elapsed + performance.now() - started;
      if (next >= duration) { setElapsed(0); setScene((value) => (value + 1) % scenes.length); }
      else setElapsed(next);
    }, elapsed < 3600 ? 70 : duration - elapsed);
    return () => window.clearTimeout(timer);
  }, [active, inView, visible, paused, reduced, elapsed]);
  const current = scenes[scene];
  const time = reduced ? duration : elapsed;
  const sent = time >= 1400;
  const replying = time >= 2300;
  const ready = time >= 3600;
  function selectScene(index: number) { setScene(index); setElapsed(0); }
  return <div className={`preview-conversation live-preview feature-preview ${paused ? "is-paused" : ""}`} ref={ref}>
    <div className="demo-feature-tabs" aria-label="Explore Sonia features">
      {scenes.map(({ label, icon: Icon }, index) => <button key={label} type="button" aria-pressed={scene === index} onClick={() => selectScene(index)}><Icon size={14} />{label}</button>)}
    </div>
    <div className="preview-transcript" key={scene}>
      <p className="sr-only">Illustrative demo. {current.prompt} {current.title} {current.copy}</p>
      <div aria-hidden="true" className={`preview-question-slot ${sent ? "is-visible" : ""}`}><div className="preview-question">{current.prompt}</div></div>
      <div className={`preview-answer ${sent ? "is-visible" : ""}`}>
        <Emblem /><div className="preview-answer-copy">
          <span className="mono">SONIA</span>
          <div className="demo-answer-reserved"><div className={`preview-stream is-complete ${replying ? "" : "demo-copy-pending"}`} aria-hidden={!replying}><p>{current.title}</p><p>{current.copy} <sup className="demo-citation-number" aria-label="Source 1">1</sup></p></div>{!replying && <div className="preview-thinking"><span /><span /><span /><small>{current.activity}</small></div>}</div>
          <div className={`demo-output ${ready ? "is-ready" : ""}`}><DemoOutput scene={current.id} /></div>
          <details className={`preview-source demo-evidence ${ready ? "is-visible" : ""}`}>
            <summary><FileText size={12} /><span><span className="demo-citation-number">1</span> {current.source}</span><span className="demo-evidence-hint">View source</span></summary>
            <div className="demo-evidence-quote"><span className="mono">ILLUSTRATIVE SOURCE EXCERPT</span><blockquote>“{current.excerpt}”</blockquote></div>
          </details>
        </div>
      </div>
    </div>
    <div className="preview-demo-controls">
      <span className="mono">0{scene + 1} / {current.label} · illustrative demo</span>
      <div className="demo-playback"><button type="button" disabled={!!reduced} onClick={() => setPaused((value) => !value)} aria-label={paused ? "Play feature demo" : "Pause feature demo"}>{paused ? <Play size={12} /> : <Pause size={12} />}{paused ? "Play" : "Pause"}</button><button type="button" onClick={() => selectScene(scene)} disabled={!!reduced} aria-label="Replay conversation demo"><RotateCcw size={12} />Replay</button></div>
    </div>
    <Link href="/chat" className="preview-composer" aria-label="Open Sonia workspace"><span className="preview-placeholder">{sent ? "What would you like to explore?" : current.prompt.slice(0, Math.floor(time / 28)) || "Bring your question…"}</span><ArrowUpRight size={18} /></Link>
  </div>;
}
