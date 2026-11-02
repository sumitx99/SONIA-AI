"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useInView, useReducedMotion } from "motion/react";
import { ArrowUpRight, FileText, Image as ImageIcon, RotateCcw } from "lucide-react";
import { Emblem } from "@/components/brand";
import { useLandingAnimation } from "@/components/landing-motion";

const prompt = "What gives an idea lasting value?";
const introduction = "The patience to see it clearly.";
const explanation =
  "The author describes original thought as an act of attention: looking closely, questioning familiar assumptions, and allowing connections to emerge. An idea gains depth when we give it time to be understood.";
const answer = `${introduction}\n${explanation}`;
const typingStart = 450;
const typingEnd = typingStart + prompt.length * 43;
const sentAt = typingEnd + 450;
const responseAt = sentAt + 850;
const completeAt = responseAt + answer.length * 23;
// After the answer, the figure from the cited page is found, then drawn in.
const imageAt = completeAt + 500;
const imageReadyAt = imageAt + 1500;
const cycleEnd = imageReadyAt + 2200 + 4500;

/** An illustrative figure, as if extracted from page 12; its strokes draw themselves in. */
function PreviewFigureArt() {
  const nodes = [
    { x: 52, label: "Look closely" },
    { x: 160, label: "Question" },
    { x: 268, label: "Connect" },
  ];
  return (
    <svg className="preview-figure-art" viewBox="0 0 320 150" role="img"
      aria-label="Diagram: look closely, question, connect, leading to depth">
      {nodes.map((node, index) => (
        <g key={node.label}>
          <circle cx={node.x} cy="52" r="26" pathLength={1} className="figure-stroke"
            style={{ animationDelay: `${index * 0.35}s` }} />
          <circle cx={node.x} cy="52" r="4" className="figure-dot" style={{ animationDelay: `${0.4 + index * 0.35}s` }} />
          <text x={node.x} y="100" className="figure-label" style={{ animationDelay: `${0.5 + index * 0.35}s` }}>
            {node.label}
          </text>
        </g>
      ))}
      {[[80, 132], [188, 240]].map(([from, to], index) => (
        <path key={from} d={`M${from} 52 H${to}`} pathLength={1} className="figure-stroke figure-link"
          style={{ animationDelay: `${0.25 + index * 0.35}s` }} />
      ))}
      <path d="M52 112 C 52 136, 268 136, 268 112" pathLength={1} className="figure-stroke figure-arc"
        style={{ animationDelay: "1.1s" }} />
      <text x="160" y="145" className="figure-label figure-depth" style={{ animationDelay: "1.6s" }}>depth</text>
    </svg>
  );
}

export function ConversationPreview() {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { amount: 0.3 });
  const { active } = useLandingAnimation();
  const reduced = useReducedMotion();
  const [elapsed, setElapsed] = useState(0);
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    const update = () => setVisible(!document.hidden);
    update();
    document.addEventListener("visibilitychange", update);
    return () => document.removeEventListener("visibilitychange", update);
  }, []);

  useEffect(() => {
    if (!active || !inView || !visible) return;
    // Only render while characters change, or at a phase boundary.
    // The thinking and completed states need no background render loop.
    const delay =
      elapsed < typingStart
        ? typingStart - elapsed
        : elapsed < typingEnd
          ? 55
          : elapsed < sentAt
            ? sentAt - elapsed
            : elapsed < responseAt
              ? responseAt - elapsed
              : elapsed < completeAt
                ? 65
                : elapsed < imageAt
                  ? imageAt - elapsed
                  : elapsed < imageReadyAt
                    ? imageReadyAt - elapsed
                    : cycleEnd - elapsed;
    const started = performance.now();
    const timer = window.setTimeout(
      () => {
        const delta = performance.now() - started;
        setElapsed((value) => (value + delta >= cycleEnd ? 0 : value + delta));
      },
      Math.max(16, delay),
    );
    return () => window.clearTimeout(timer);
  }, [active, inView, visible, elapsed]);

  const time = reduced ? cycleEnd - 1 : elapsed;
  const sent = time >= sentAt;
  const responding = time >= responseAt;
  const complete = time >= completeAt;
  const imageShown = time >= imageAt;
  const imageReady = time >= imageReadyAt;
  const typedPrompt = prompt.slice(
    0,
    Math.max(0, Math.floor((time - typingStart) / 43)),
  );
  const streamedAnswer = answer.slice(
    0,
    Math.max(0, Math.floor((time - responseAt) / 23)),
  );
  const [firstParagraph, secondParagraph] = streamedAnswer.split("\n");
  const step = imageReady
    ? "04 / A clearer perspective"
    : imageShown
      ? "03 / Finding the figure"
      : complete
    ? "03 / A clearer perspective"
    : sent
      ? "02 / Reading between the lines"
      : "01 / A question, considered";

  return (
    <div className="preview-conversation live-preview" ref={ref}>
      <p className="sr-only">
        Illustrative conversation: {prompt} Sonia replies: {introduction}{" "}
        {explanation} Source: The creative process.pdf, page 12, with the figure from that
        page: look closely, question, connect, leading to depth.
      </p>
      <div className="preview-transcript" aria-hidden="true">
        <div className={`preview-question-slot ${sent ? "is-visible" : ""}`}>
          <div className="preview-question">{prompt}</div>
        </div>
        <div className={`preview-answer ${sent ? "is-visible" : ""}`}>
          <Emblem />
          <div className="preview-answer-copy">
            <span className="mono">SONIA</span>
            {/* The finished answer is laid out invisibly underneath, so the frame has its final
                height from the start and streaming text never pushes anything down. */}
            <div className="preview-stack">
              <div className="preview-stream is-complete preview-ghost">
                <p>{introduction}</p>
                <p>{explanation}</p>
              </div>
              {!responding ? (
                <div className="preview-thinking">
                  <span />
                  <span />
                  <span />
                  <small>Considering the passage…</small>
                </div>
              ) : (
                <div
                  className={`preview-stream ${complete ? "is-complete" : ""}`}
                >
                  <p>
                    {firstParagraph}
                    {!complete && !secondParagraph && (
                      <span className="typing-caret" />
                    )}
                  </p>
                  {secondParagraph !== undefined && (
                    <p>
                      {secondParagraph}
                      {!complete && <span className="typing-caret" />}
                    </p>
                  )}
                </div>
              )}
            </div>
            <span className={`preview-source ${complete ? "is-visible" : ""}`}>
              <FileText size={12} /> The creative process.pdf · p. 12
            </span>
            {/* Always laid out so the frame doesn't jump when the figure arrives. */}
            <figure className={`preview-figure ${imageShown ? "is-visible" : ""} ${imageReady ? "is-ready" : ""}`}>
              <div className="preview-figure-mat">
                {imageReady ? (
                  <PreviewFigureArt />
                ) : (
                  <div className="preview-figure-skeleton">
                    <ImageIcon size={18} strokeWidth={1.4} />
                    <small>Finding the figure on page 12…</small>
                  </div>
                )}
              </div>
              <figcaption>
                <strong>Page 12 · Image 1</strong>
                <span>The creative process › Attention</span>
              </figcaption>
            </figure>
          </div>
        </div>
      </div>
      <div className="preview-demo-controls">
        <span className="mono" aria-hidden="true">
          {step}
        </span>
        <button
          type="button"
          onClick={() => setElapsed(0)}
          disabled={!!reduced}
          aria-label="Replay conversation demo"
        >
          <RotateCcw size={12} />
          <span>Replay</span>
        </button>
      </div>
      <Link
        href="/chat"
        className={`preview-composer ${!sent && typedPrompt ? "is-typing" : ""}`}
        aria-label="Open Sonia workspace"
      >
        <span aria-hidden="true">
          {!sent ? (
            <>
              {typedPrompt || (
                <span className="preview-placeholder">
                  Ask a question about your document…
                </span>
              )}
              {time >= typingStart && <span className="typing-caret" />}
            </>
          ) : (
            <span className="preview-placeholder">
              Where will your curiosity take you?
            </span>
          )}
        </span>
        <span className="preview-send" aria-hidden="true">
          <ArrowUpRight size={18} />
        </span>
      </Link>
    </div>
  );
}
