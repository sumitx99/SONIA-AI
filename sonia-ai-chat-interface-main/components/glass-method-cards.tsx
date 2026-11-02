"use client";

import { useRef, useState, type PointerEvent } from "react";
import { ArrowUpRight, RefreshCw } from "lucide-react";
import { useReducedMotion } from "motion/react";
import { ClarityArt, PagesArt, ThreadArt } from "@/components/method-illustrations";

const ART = { pages: PagesArt, thread: ThreadArt, clarity: ClarityArt };

export interface MethodStep {
  n: string;
  label: string;
  title: string;
  text: string;
  art: keyof typeof ART;
}

const PERSPECTIVE = "perspective(1100px)";

function GlassCard({ step, index }: { step: MethodStep; index: number }) {
  const tilt = useRef<HTMLDivElement>(null);
  const card = useRef<HTMLDivElement>(null);
  const turning = useRef(false);
  // The side the user currently wants; a flip finishing out of date turns again.
  const wanted = useRef(false);
  const shown = useRef(false);
  const [flipped, setFlipped] = useState(false);
  const reduce = useReducedMotion();
  const Art = ART[step.art];

  // Pointer position drives the tilt and the specular highlight.
  function onPointerMove(event: PointerEvent<HTMLDivElement>) {
    if (reduce || event.pointerType !== "mouse" || !tilt.current) return;
    const box = tilt.current.getBoundingClientRect();
    const x = (event.clientX - box.left) / box.width;
    const y = (event.clientY - box.top) / box.height;
    tilt.current.style.setProperty("--mx", `${x * 100}%`);
    tilt.current.style.setProperty("--my", `${y * 100}%`);
    tilt.current.style.setProperty("--rx", `${(0.5 - y) * 8}deg`);
    tilt.current.style.setProperty("--ry", `${(x - 0.5) * 10}deg`);
  }

  function onPointerLeave(event: PointerEvent<HTMLDivElement>) {
    for (const name of ["--mx", "--my", "--rx", "--ry"]) tilt.current?.style.removeProperty(name);
    if (event.pointerType === "mouse") turnTo(false);
  }

  // Turned in two halves on one element (edge-on swap) rather than two 3D faces:
  // backdrop-filter is lost inside preserve-3d, and the glass is the point.
  async function turnTo(back: boolean) {
    wanted.current = back;
    const element = card.current;
    if (!element || turning.current) return;
    while (shown.current !== wanted.current) {
      const target = wanted.current;
      shown.current = target;
      if (reduce) {
        setFlipped(target);
        break;
      }
      turning.current = true;
      const direction = target ? 1 : -1;
      await element.animate(
        [{ transform: `${PERSPECTIVE} rotateY(0deg)` }, { transform: `${PERSPECTIVE} rotateY(${90 * direction}deg)` }],
        { duration: 220, easing: "cubic-bezier(0.55, 0, 1, 0.45)" },
      ).finished;
      setFlipped(target);
      await element.animate(
        [{ transform: `${PERSPECTIVE} rotateY(${-90 * direction}deg)` }, { transform: `${PERSPECTIVE} rotateY(0deg)` }],
        { duration: 420, easing: "cubic-bezier(0.22, 1.25, 0.36, 1)" },
      ).finished;
      turning.current = false;
    }
  }

  return (
    <div ref={tilt} className="glass-tilt" onPointerMove={onPointerMove} onPointerLeave={onPointerLeave}
      onPointerEnter={(event) => event.pointerType === "mouse" && turnTo(true)}
      style={{ animationDelay: `${index * 0.12}s` }}>
      {/* Mouse: hover shows the details. Touch: tap the card. Keyboard: the button. */}
      <div ref={card} className={`glass-card ${flipped ? "is-back" : ""}`}
        onClick={(event) => {
          if ((event.nativeEvent as globalThis.PointerEvent).pointerType !== "mouse") turnTo(!wanted.current);
        }}>
        <span className="glass-sheen" aria-hidden />
        <div className="glass-top">
          <span className="glass-pill">{step.n} — {step.label}</span>
          <button type="button" className="glass-flip" aria-pressed={flipped}
            onClick={(event) => { event.stopPropagation(); turnTo(!wanted.current); }}
            aria-label={flipped ? `Show “${step.title}”` : `Read more about “${step.title}”`}>
            <RefreshCw size={15} strokeWidth={1.6} />
          </button>
        </div>
        {/* Both sides stay readable to screen readers; CSS only fades the hidden side. */}
        <div className="glass-face glass-front">
          <div className="glass-photo">
            <Art />
          </div>
          <h3>{step.title}</h3>
        </div>
        <div className="glass-face glass-back">
          <p>{step.text}</p>
          <ArrowUpRight size={22} strokeWidth={1.2} aria-hidden />
        </div>
      </div>
    </div>
  );
}

export function GlassMethodCards({ steps }: { steps: MethodStep[] }) {
  return (
    <div className="glass-stage">
      <div className="glass-scene" aria-hidden>
        <span className="glass-blob glass-blob-a" />
        <span className="glass-blob glass-blob-b" />
        <span className="glass-blob glass-blob-c" />
      </div>
      <div className="glass-grid">
        {steps.map((step, index) => <GlassCard key={step.n} step={step} index={index} />)}
      </div>
    </div>
  );
}
