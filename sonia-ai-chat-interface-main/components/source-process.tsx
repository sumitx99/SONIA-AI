"use client";

import { useEffect, useRef, useState } from "react";
import { useInView } from "motion/react";
import { useLandingAnimation } from "@/components/landing-motion";
import { ArrowRight, Check, FileText, ImageIcon, MessageSquare, Upload } from "lucide-react";

const steps = [
  { title: "Bring your document", label: "Upload", text: "Drop in a research paper, report, or your lecture notes. Your next discovery starts with what you already have.", icon: Upload },
  { title: "Follow your curiosity", label: "Ask", text: "Ask a question, unpack a concept, or compare ideas. Keep the conversation going as your thinking develops.", icon: MessageSquare },
  { title: "Go back to the source", label: "Discover", text: "Explore the relevant figures and page references alongside your answer. Keep the detail in sight.", icon: ImageIcon },
];

export function SourceProcess() {
  const [selected, setSelected] = useState(0);
  const container = useRef<HTMLDivElement>(null);
  const inView = useInView(container, { amount: 0.2 });
  const { active } = useLandingAnimation();
  const [visible, setVisible] = useState(true);
  useEffect(() => {
    const update = () => setVisible(!document.hidden);
    update();
    document.addEventListener("visibilitychange", update);
    return () => document.removeEventListener("visibilitychange", update);
  }, []);
  return (
    <div className="process-explorer" ref={container} data-animate={active && inView && visible} data-step={selected}>
      <div className="process-steps" role="tablist" aria-label="Explore how Sonia works" aria-orientation="vertical">
        {steps.map((step, index) => (
          <button key={step.label} type="button" role="tab" id={`process-tab-${index}`} aria-controls="process-panel" aria-selected={selected === index}
            onClick={() => setSelected(index)}
            onKeyDown={(event) => {
              const next = event.key === "ArrowDown" ? (index + 1) % 3 : event.key === "ArrowUp" ? (index + 2) % 3 : event.key === "Home" ? 0 : event.key === "End" ? 2 : null;
              if (next !== null) { event.preventDefault(); setSelected(next); document.getElementById(`process-tab-${next}`)?.focus(); }
            }}
            tabIndex={selected === index ? 0 : -1} className="process-step">
            <span className="process-step-number">0{index + 1}</span>
            <span className="process-step-copy"><span className="process-step-label">{step.label}</span><strong>{step.title}</strong><span className="process-step-description">{step.text}</span></span>
            <ArrowRight size={18} aria-hidden="true" />
          </button>
        ))}
      </div>
      <div className="process-preview" role="tabpanel" id="process-panel" aria-labelledby={`process-tab-${selected}`} tabIndex={0}>
        <div className="process-preview-top"><span><i /><i /><i /></span><span>SONIA / WORKSPACE PREVIEW</span><span className="process-preview-status">●</span></div>
        <div className="process-preview-body" key={selected}>
          <div className="process-demo-file"><FileText size={16} /><span>The creative process.pdf</span><Check size={14} /></div>
          {selected === 0 ? (
            <div className="process-upload-demo"><div className="process-file-stack" aria-hidden="true"><FileText size={45} strokeWidth={1.2} /></div><h3>A place for your next idea.</h3><p>Start with a document.<br />Let your questions lead the way.</p><span className="process-demo-pill"><Upload size={14} /> Upload a PDF</span><span className="process-demo-note">Illustrative preview</span></div>
          ) : (
            <div className="process-chat-demo"><span className="process-question">What gives an idea lasting value?</span><div className="process-answer"><span className="process-answer-name">S / SONIA</span><h3>The patience to see it clearly.</h3><p>The author describes original thought as an act of attention: looking closely, questioning assumptions, and allowing connections to emerge.</p>{selected === 2 && <div className="process-source-figure"><span><ImageIcon size={13} /> FIGURE / PAGE 12</span><div className="process-figure-nodes"><span>Observe</span><ArrowRight size={16} /><span>Question</span><ArrowRight size={16} /><span>Connect</span></div><small>Follow the thread. Find the insight.</small></div>}<span className="process-citation"><FileText size={12} /> The creative process.pdf · Page 12</span></div><span className="process-demo-note">Illustrative answer and source</span></div>
          )}
        </div>
        <div className="process-preview-bottom"><span>YOUR SOURCES. YOUR PERSPECTIVE.</span><span>0{selected + 1} / 03</span></div>
      </div>
    </div>
  );
}
