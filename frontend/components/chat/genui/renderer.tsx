"use client";

import dynamic from "next/dynamic";
import { Fragment, useId, useMemo, useState } from "react";
import { useReducedMotion } from "motion/react";
import { parseGenUI, type GenUINode, type GenUISpec } from "@/lib/genui";
import type { Citation } from "@/lib/api";
import { Diagram } from "./diagram";
import styles from "./genui.module.css";

const Chart = dynamic(() => import("./chart").then(module => module.Chart), { ssr: false });
type State = GenUISpec["initial_state"];

function Slider({ node, value, onChange }: {
  node: Extract<GenUINode, { type: "slider" }>; value: number; onChange: (value: number) => void;
}) {
  const id = useId();
  return <div className={styles.slider}>
    <label htmlFor={id}>{node.label}</label>
    <output htmlFor={id}>{value}</output>
    <input id={id} type="range" min={node.min} max={node.max} step={node.step} value={value}
      onChange={event => onChange(event.currentTarget.valueAsNumber)} />
  </div>;
}

function Interface({ spec, citations, reduceMotion }: {
  spec: GenUISpec; citations?: Citation[]; reduceMotion: boolean;
}) {
  const [overrides, setOverrides] = useState<State>({});
  const systemReducedMotion = useReducedMotion();
  const reducedMotion = reduceMotion || Boolean(systemReducedMotion);
  const state = { ...spec.initial_state, ...overrides };
  const setValue = (key: string, value: State[string]) =>
    setOverrides(previous => ({ ...previous, [key]: value }));

  const children = new Map<string, GenUINode[]>();
  for (const node of spec.nodes) {
    if (!node.parent) continue;
    const siblings = children.get(node.parent) ?? [];
    siblings.push(node);
    children.set(node.parent, siblings);
  }

  function renderNode(node: GenUINode): React.ReactNode {
    const condition = node.visible_when;
    if (condition && state[condition.key] !== condition.equals) return null;
    switch (node.type) {
      case "column":
      case "row":
      case "card": {
        const content = (children.get(node.id) ?? []).map(child => {
          const rendered = renderNode(child);
          return rendered && <Fragment key={child.id}>{rendered}</Fragment>;
        }).filter(Boolean);
        if (!content.length) return null;
        if (node.type === "card") return <section className={styles.card}>
          {node.title && <h3 className={styles.title}>{node.title}</h3>}
          <div className={styles.column}>{content}</div>
        </section>;
        return <div className={node.type === "row" ? styles.row : styles.column}>{content}</div>;
      }
      case "text":
        return <p className={styles.text}>{node.content}{node.state_key && <> <strong>{String(state[node.state_key])}</strong></>}</p>;
      case "button":
        return <button className={styles.button} type="button" aria-pressed={state[node.key] === node.value}
          onClick={() => setValue(node.key, node.value)}>{node.label}</button>;
      case "slider":
        return <Slider node={node} value={Number(state[node.key])} onChange={value => setValue(node.key, value)} />;
      case "diagram":
        return <Diagram spec={node} reducedMotion={reducedMotion} />;
      case "chart":
        return <Chart spec={node} state={state} citations={citations} reducedMotion={reducedMotion} />;
    }
  }

  const content = renderNode(spec.nodes[0]);
  return content ? <div className={styles.root}>{content}</div> : null;
}

export function GenUIRenderer({ source, citations, reduceMotion }: {
  source: unknown; citations?: Citation[]; reduceMotion: boolean;
}) {
  const spec = useMemo(() => parseGenUI(source), [source]);
  if (!spec) return null;
  return <Interface spec={spec} citations={citations} reduceMotion={reduceMotion} />;
}
