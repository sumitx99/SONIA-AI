"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import Image from "next/image";
import { useInView, useReducedMotion } from "motion/react";
import { ArrowUpRight, ChartNoAxesCombined, Check, FileText, Globe, ImageIcon, Pause, Play, Plug, RotateCcw, Table2 } from "lucide-react";
import { Emblem } from "@/components/brand";
import { MarkdownTable } from "@/components/chat/markdown-table";
import documentImageStyles from "@/components/chat/document-image.module.css";
import { useLandingAnimation } from "./landing-motion";

const scenes = [
  { label: "Graphs", icon: ChartNoAxesCombined, prompt: "Plot revenue from this report by quarter.", title: "A year of steady growth.", copy: "Revenue rose every quarter. Here’s the trend, drawn from your report.", activity: "Reading quarterly revenue…", source: "Quarterly report.pdf · p. 4" },
  { label: "Tables", icon: Table2, prompt: "Compare these three plans in a table.", title: "The details, side by side.", copy: "A clear comparison you can copy into your spreadsheet or document.", activity: "Comparing the plan details…", source: "Product plans.pdf · p. 2" },
  { label: "Web search", icon: Globe, prompt: "Explore how attention shapes creative thinking.", title: "Make room for a better idea.", copy: "Focused attention gives ideas time to develop. Explore the findings, images, and sources together.", activity: "Searching and reading sources…", source: "Web research · illustrative sources and imagery" },
  { label: "MCP tools", icon: Plug, prompt: "Find my project notes using connected tools.", title: "Your tools, in the conversation.", copy: "A connected MCP server finds your notes. Actions that make changes ask you first.", activity: "Calling connected notes tool…", source: "Project notes · connected MCP server" },
  { label: "PDF images", icon: ImageIcon, prompt: "Show the creative process figure from this PDF.", title: "The figure, alongside the explanation.", copy: "The process moves from observation to reflection, then connection. Here’s the original figure from the page.", activity: "Finding the figure in your PDF…", source: "The creative process.pdf · p. 6 · Image 1" },
];
const sourceExcerpts = [
  "Quarterly revenue (USD thousands): Q1 24, Q2 38, Q3 46, Q4 64.",
  "Starter: Personal projects, 5 GB. Team: Working together, 50 GB. Business: Growing teams, 250 GB.",
  "Focused attention gives ideas time to develop; reflection creates space to connect ideas.",
  "Launch checklist: Design review, milestones, and next steps.",
  "Figure 1. The creative process: Observe → Reflect → Connect.",
];
const duration = 9000;

function DemoOutput({ scene }: { scene: number }) {
  if (scene === 0) return <div className="demo-chart" role="img" aria-label="Illustrative quarterly revenue, 24, 38, 46, 64 thousand dollars">
    <div className="demo-output-heading"><span>REVENUE / USD THOUSANDS</span><span>2026</span></div>
    <svg viewBox="0 0 480 142" aria-hidden="true">
      {[20, 60, 100].map((y) => <path key={y} d={`M24 ${y} H456`} className="demo-grid-line" />)}
      <path d="M24 108 L168 83 L312 68 L456 32 L456 120 L24 120Z" className="demo-chart-area" />
      <path d="M24 108 L168 83 L312 68 L456 32" pathLength="1" className="demo-chart-line" />
      {[[24, 108], [168, 83], [312, 68], [456, 32]].map(([x, y]) => <circle key={x} cx={x} cy={y} r="4" />)}
      {["Q1", "Q2", "Q3", "Q4"].map((q, i) => <text key={q} x={24 + i * 144} y="139" textAnchor="middle">{q}</text>)}
    </svg>
  </div>;
  if (scene === 1) return <div className="demo-table-wrap markdown-body"><MarkdownTable>
    <caption className="sr-only">Illustrative plan comparison</caption>
    <thead><tr><th>Plan</th><th>For</th><th>Storage</th></tr></thead>
    <tbody>{[["Starter", "Personal projects", "5 GB"], ["Team", "Working together", "50 GB"], ["Business", "Growing teams", "250 GB"]].map((row) => <tr key={row[0]}>{row.map((cell) => <td key={cell}>{cell}</td>)}</tr>)}</tbody>
  </MarkdownTable></div>;
  if (scene === 2) return <div className="demo-research">
    <div className="demo-research-status"><Globe size={13} /><span>Web search complete</span><Check size={13} /></div>
    <div className="demo-research-result">
      <figure className="demo-research-image"><Image src="/images/sonia-marble-mind.png" alt="Illustrative marble sculpture representing creative thought" fill sizes="(max-width: 640px) 100px, 140px" /><figcaption>Visual inspiration</figcaption></figure>
      <div className="demo-research-summary"><span className="demo-output-heading">EXPLORE THE FINDINGS</span><strong>Attention & creative thinking</strong><span>Time to reflect. Space to connect ideas.</span><div className="demo-source-chips"><span>Research <ArrowUpRight size={10} /></span><span>Further reading <ArrowUpRight size={10} /></span></div></div>
    </div>
  </div>;
  if (scene === 4) return <figure className={`demo-pdf-figure ${documentImageStyles.figure}`}>
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
  return <div className="preview-conversation live-preview feature-preview" ref={ref}>
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
          <div className={`demo-output ${ready ? "is-ready" : ""}`}><DemoOutput scene={scene} /></div>
          <details className={`preview-source demo-evidence ${ready ? "is-visible" : ""}`}>
            <summary><FileText size={12} /><span><span className="demo-citation-number">1</span> {current.source}</span><span className="demo-evidence-hint">View source</span></summary>
            <div className="demo-evidence-quote"><span className="mono">ILLUSTRATIVE SOURCE EXCERPT</span><blockquote>“{sourceExcerpts[scene]}”</blockquote></div>
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
