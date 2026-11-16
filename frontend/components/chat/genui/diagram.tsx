"use client";

import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { MotionConfig, motion } from "motion/react";
import { ChevronLeft, ChevronRight, Pause, Play, RotateCcw } from "lucide-react";
import { DIAGRAM_METRICS as M, layoutDiagram, type Measure, type PlacedNode } from "@/lib/diagram-layout";
import type { DiagramSpec } from "@/lib/genui";
import styles from "./genui.module.css";

/** Timing and emphasis of every diagram transition. */
const MOTION = {
  enterSeconds: 0.4,
  staggerSeconds: 0.045,
  changeSeconds: 0.32,
  drawSeconds: 0.6,
  packetSeconds: 1.5,
  dimmedOpacity: 0.3,
  hiddenScale: 0.92,
  // How long a step stays up during playback: time to see the motion plus time to read the caption.
  stepBaseMs: 1800,
  stepPerCharacterMs: 45,
  stepMaxMs: 8000,
} as const;
const TEXT = {
  label: [M.labelSize, M.labelWeight],
  detail: [M.detailSize, M.detailWeight],
  edgeLabel: [M.edgeLabelSize, M.edgeLabelWeight],
} as const;
// Average glyph width as a share of the font size, used only where a canvas is unavailable.
const FALLBACK_GLYPH_RATIO = 0.58;
const OVERVIEW = -1;

/** Measures text in the font the diagram is actually drawn with, once that font is known. */
function useMeasure(element: React.RefObject<HTMLElement | null>): Measure | null {
  const [font, setFont] = useState<{ family: string; loaded: boolean } | null>(null);
  useLayoutEffect(() => {
    if (!element.current) return;
    const family = getComputedStyle(element.current).fontFamily;
    let current = true;
    setFont({ family, loaded: false });
    // Web fonts may arrive after the first paint and change every width.
    document.fonts?.ready.then(() => { if (current) setFont({ family, loaded: true }); });
    return () => { current = false; };
  }, [element]);
  return useMemo(() => {
    if (!font) return null;
    const context = document.createElement("canvas").getContext("2d");
    return (text, role) => {
      const [size, weight] = TEXT[role];
      if (!context) return text.length * size * FALLBACK_GLYPH_RATIO;
      context.font = `${weight} ${size}px ${font.family}`;
      return context.measureText(text).width;
    };
  }, [font]);
}

function Shape({ node }: { node: PlacedNode }) {
  const { width, height } = node;
  switch (node.kind) {
    case "decision":
      return <polygon points={`${width / 2},0 ${width},${height / 2} ${width / 2},${height} 0,${height / 2}`} />;
    case "actor":
      return <rect width={width} height={height} rx={height / 2} />;
    case "data": {
      const cap = M.cylinderCap;
      const arc = `A${width / 2},${cap} 0 0`;
      return <>
        <path d={`M0,${cap}${arc} 1 ${width},${cap}V${height - cap}${arc} 1 0,${height - cap}Z`} />
        <path className={styles.inner} d={`M0,${cap}${arc} 0 ${width},${cap}`} />
      </>;
    }
    case "queue":
      return <>
        <rect width={width} height={height} rx={M.cornerRadius} />
        {Array.from({ length: M.queueSlots }, (_, slot) => {
          const x = width - M.queueSlot * (slot + 1.5);
          return <path key={slot} className={styles.inner} d={`M${x},0V${height}`} />;
        })}
      </>;
    default:
      return <rect width={width} height={height} rx={M.cornerRadius} />;
  }
}

function NodeText({ node }: { node: PlacedNode }) {
  const x = node.textX - node.x;
  const top = node.textY - node.y;
  const labelLine = M.labelSize * M.lineHeight;
  const detailLine = M.detailSize * M.lineHeight;
  const detailTop = top + node.lines.length * labelLine + M.detailGap;
  return <>
    <text textAnchor="middle" dominantBaseline="central" fontSize={M.labelSize} fontWeight={M.labelWeight}>
      {node.lines.map((line, index) => <tspan key={index} x={x} y={top + (index + 0.5) * labelLine}>{line}</tspan>)}
    </text>
    {node.detail.length > 0 &&
      <text className={styles.detail} textAnchor="middle" dominantBaseline="central" fontSize={M.detailSize} fontWeight={M.detailWeight}>
        {node.detail.map((line, index) => <tspan key={index} x={x} y={detailTop + (index + 0.5) * detailLine}>{line}</tspan>)}
      </text>}
  </>;
}

/** What a walkthrough step shows: which parts exist yet, and which carry the reader's attention. */
function stepView(spec: DiagramSpec, step: number) {
  const ends = new Map(spec.edges.map(edge => [edge.id, [edge.source, edge.target]]));
  const touched = (from: number, to: number) => {
    const nodes = new Set<string>();
    const edges = new Set<string>();
    for (const item of spec.steps.slice(from, to)) {
      item.focus.forEach(id => nodes.add(id));
      for (const id of item.flow) {
        edges.add(id);
        ends.get(id)!.forEach(end => nodes.add(end));
      }
    }
    return { nodes, edges };
  };
  const current = step === OVERVIEW ? null : touched(step, step + 1);
  const hiddenNodes = new Set<string>();
  const hiddenEdges = new Set<string>();
  if (spec.build && current) {
    // Parts a later step introduces wait for it; parts no step mentions are context from the start.
    const ever = touched(0, spec.steps.length);
    const shown = touched(0, step + 1);
    ever.nodes.forEach(id => { if (!shown.nodes.has(id)) hiddenNodes.add(id); });
    for (const edge of spec.edges) {
      if ((ever.edges.has(edge.id) && !shown.edges.has(edge.id)) ||
          hiddenNodes.has(edge.source) || hiddenNodes.has(edge.target)) hiddenEdges.add(edge.id);
    }
  }
  return { current, hiddenNodes, hiddenEdges };
}

export function Diagram({ spec, reducedMotion }: { spec: DiagramSpec; reducedMotion: boolean }) {
  const marker = useId();
  const titleId = useId();
  const descriptionId = useId();
  const container = useRef<HTMLDivElement>(null);
  const measure = useMeasure(container);
  const layout = useMemo(() => measure && layoutDiagram(spec, measure), [spec, measure]);
  const [step, setStep] = useState(OVERVIEW);
  const [playing, setPlaying] = useState(false);
  const [entered, setEntered] = useState(false);
  const last = spec.steps.length - 1;
  const caption = spec.steps[step]?.caption;

  useEffect(() => {
    if (reducedMotion) setPlaying(false);
  }, [reducedMotion]);
  useEffect(() => {
    if (!playing) return;
    const wait = Math.min(MOTION.stepMaxMs, MOTION.stepBaseMs + MOTION.stepPerCharacterMs * (caption?.length ?? 0));
    const timer = setTimeout(() => {
      if (step >= last) setPlaying(false);
      else setStep(step + 1);
    }, wait);
    return () => clearTimeout(timer);
  }, [playing, step, last, caption]);
  useEffect(() => {
    if (!layout) return;
    const timer = setTimeout(() => setEntered(true),
      (MOTION.enterSeconds + MOTION.staggerSeconds * layout.nodes.length) * 1000);
    return () => clearTimeout(timer);
  }, [layout]);

  const view = useMemo(() => stepView(spec, step), [spec, step]);
  const labels = new Map(spec.nodes.map(node => [node.id, node.label]));
  const change = { duration: reducedMotion ? 0 : MOTION.changeSeconds };
  const finished = step === last && !playing;

  return <figure className={styles.figure}>
    <figcaption id={titleId} className={styles.title}>{spec.title}</figcaption>
    <div ref={container} className={styles.diagram} tabIndex={0} role="region" aria-labelledby={titleId}>
      {layout && <MotionConfig reducedMotion={reducedMotion ? "always" : "never"}>
        <svg width={layout.width} height={layout.height} viewBox={`0 0 ${layout.width} ${layout.height}`}
          style={{ minWidth: Math.round(layout.width * M.minScale) }}
          role="img" aria-labelledby={titleId} aria-describedby={descriptionId}>
          <desc id={descriptionId}>
            {spec.nodes.map(node => node.label).join(", ")}. {spec.edges.map(edge =>
              `${labels.get(edge.source)} → ${labels.get(edge.target)}${edge.label ? ` (${edge.label})` : ""}`).join("; ")}
          </desc>
          <defs>
            {(["edge", "flow"] as const).map(kind =>
              <marker key={kind} id={`${marker}${kind}`} viewBox="0 0 10 10" refX="9" refY="5"
                markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                <path d="M0 1L10 5L0 9Z" className={kind === "flow" ? styles.flowArrow : styles.arrow} />
              </marker>)}
          </defs>
          {layout.groups.map(group => {
            const hidden = spec.nodes.every(node => node.group !== group.id || view.hiddenNodes.has(node.id));
            return <motion.g key={group.id} className={styles.group} initial={{ opacity: 0 }}
              animate={{ opacity: hidden ? 0 : 1 }} transition={change}>
              <rect x={group.x} y={group.y} width={group.width} height={group.height} rx={M.cornerRadius} />
              <text x={group.x + M.groupPadding / 2} y={group.y + M.groupLabelHeight / 2} dominantBaseline="central"
                fontSize={M.detailSize} fontWeight={M.labelWeight}>{group.label}</text>
            </motion.g>;
          })}
          {layout.edges.map(edge => {
            const hidden = view.hiddenEdges.has(edge.id);
            const flowing = Boolean(view.current?.edges.has(edge.id));
            const opacity = hidden ? 0 : view.current && !flowing ? MOTION.dimmedOpacity : 1;
            return <g key={edge.id} aria-hidden="true">
              <motion.path d={edge.path} className={styles.edge} data-dashed={edge.dashed}
                markerEnd={`url(#${marker}edge)`} initial={{ opacity: 0 }} animate={{ opacity }}
                transition={{ ...change, delay: entered || reducedMotion ? 0 : MOTION.enterSeconds }} />
              {flowing && <>
                <motion.path key={step} d={edge.path} className={styles.flow} markerEnd={`url(#${marker}flow)`}
                  initial={{ pathLength: reducedMotion ? 1 : 0 }} animate={{ pathLength: 1 }}
                  transition={{ duration: reducedMotion ? 0 : MOTION.drawSeconds, ease: "easeInOut" }} />
                {!reducedMotion && <circle r={M.labelSize / 3} className={styles.packet}
                  style={{ offsetPath: `path("${edge.path}")`, animationDuration: `${MOTION.packetSeconds}s` }} />}
              </>}
              {edge.label && <motion.g className={styles.edgeLabel} initial={{ opacity: 0 }} animate={{ opacity }} transition={change}>
                <rect x={edge.label.x - edge.label.width / 2} y={edge.label.y - edge.label.height / 2}
                  width={edge.label.width} height={edge.label.height} rx={edge.label.height / 2} />
                <text x={edge.label.x} y={edge.label.y} textAnchor="middle" dominantBaseline="central"
                  fontSize={M.edgeLabelSize} fontWeight={M.edgeLabelWeight}>{edge.label.text}</text>
              </motion.g>}
            </g>;
          })}
          {layout.nodes.map((node, index) => {
            const hidden = view.hiddenNodes.has(node.id);
            const focused = Boolean(view.current?.nodes.has(node.id));
            return <g key={node.id} transform={`translate(${node.x} ${node.y})`} aria-hidden={hidden}>
              <motion.g className={styles.node} data-tone={node.tone} data-kind={node.kind} data-focused={focused}
                style={{ transformBox: "fill-box", transformOrigin: "center" }}
                initial={{ opacity: 0, scale: MOTION.hiddenScale }}
                animate={{
                  opacity: hidden ? 0 : view.current && !focused ? MOTION.dimmedOpacity : 1,
                  scale: hidden ? MOTION.hiddenScale : 1,
                }}
                transition={entered || reducedMotion ? change
                  : { duration: MOTION.enterSeconds, delay: index * MOTION.staggerSeconds, ease: "easeOut" }}>
                <title>{node.title}</title>
                <Shape node={node} />
                <NodeText node={node} />
              </motion.g>
            </g>;
          })}
        </svg>
      </MotionConfig>}
    </div>
    {last >= 0 && <div className={styles.walkthrough}>
      <div className={styles.controls} role="group" aria-label="Walkthrough">
        <button className={styles.iconButton} type="button" aria-label="Previous step" title="Previous step"
          disabled={step === OVERVIEW} onClick={() => { setPlaying(false); setStep(step - 1); }}>
          <ChevronLeft size={16} aria-hidden="true" />
        </button>
        {!reducedMotion && <button className={styles.iconButton} type="button" data-primary=""
          aria-label={playing ? "Pause" : finished ? "Replay" : "Play"} title={playing ? "Pause" : finished ? "Replay" : "Play"}
          onClick={() => {
            if (!playing && (finished || step === OVERVIEW)) setStep(0);
            setPlaying(!playing);
          }}>
          {playing ? <Pause size={16} aria-hidden="true" /> : finished ? <RotateCcw size={16} aria-hidden="true" /> : <Play size={16} aria-hidden="true" />}
        </button>}
        <button className={styles.iconButton} type="button" aria-label="Next step" title="Next step"
          disabled={step === last} onClick={() => { setPlaying(false); setStep(step + 1); }}>
          <ChevronRight size={16} aria-hidden="true" />
        </button>
        <span className={styles.position} aria-hidden="true">{step === OVERVIEW ? "–" : step + 1} / {last + 1}</span>
      </div>
      <p className={styles.caption} aria-live="polite">{caption}</p>
    </div>}
  </figure>;
}
