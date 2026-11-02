"use client";

import { useRef, type PointerEvent } from "react";
import { motion, useInView, useSpring } from "motion/react";
import { Emblem } from "@/components/brand";
import { useLandingAnimation } from "@/components/landing-motion";

export function StudioHeadline() {
  const { active } = useLandingAnimation();
  return (
    <motion.h1
      initial={active ? "hidden" : false}
      animate="visible"
      variants={{
        hidden: {},
        visible: { transition: { staggerChildren: 0.16, delayChildren: 0.1 } },
      }}
      aria-label="Old soul. New mind."
    >
      {["Old soul.", "New mind."].map((line, index) => (
        <span className="studio-headline-line" key={line}>
          <motion.span
            variants={{
              hidden: { y: "115%", rotate: 4 },
              visible: {
                y: 0,
                rotate: 0,
                transition: { duration: 1.1, ease: [0.22, 1, 0.36, 1] },
              },
            }}
          >
            {index === 1 ? <em>{line}</em> : line}
          </motion.span>
        </span>
      ))}
    </motion.h1>
  );
}

export function SculptureStage() {
  const ref = useRef<HTMLDivElement>(null);
  const { active } = useLandingAnimation();
  const inView = useInView(ref);
  const pointerX = useSpring(0, { stiffness: 70, damping: 24 });
  const tilt = useSpring(0, { stiffness: 70, damping: 24 });
  function move(event: PointerEvent<HTMLDivElement>) {
    if (!active || !inView || event.pointerType !== "mouse") return;
    const bounds = event.currentTarget.getBoundingClientRect();
    const offset = (event.clientX - bounds.left) / bounds.width - 0.5;
    pointerX.set(offset * 18);
    tilt.set(offset * 0.6);
  }
  return (
    <div
      className="studio-sculpture"
      ref={ref}
      data-in-view={inView}
      onPointerMove={move}
      onPointerLeave={() => {
        pointerX.set(0);
        tilt.set(0);
      }}
    >
      <motion.div
        className="studio-sculpture-image"
        style={{
          x: active ? pointerX : 0,
          rotate: active ? tilt : 0,
        }}
        initial={active ? { opacity: 0, scale: 1.08 } : false}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 1.5, ease: [0.22, 1, 0.36, 1] }}
      >
        <img
          src="/images/sonia-marble-mind.png"
          alt="An antique marble philosopher wrapped in a flowing red paper ribbon, with suspended manuscript pages"
          fetchPriority="high"
          width={1254}
          height={1254}
        />
      </motion.div>
      <div className="studio-orbit-label">
        <span>AN OLD-WORLD SOUL.</span>
        <Emblem />
        <span>A NEW PERSPECTIVE.</span>
      </div>
      <motion.div
        className="studio-floating-note"
        initial={active ? { opacity: 0, y: 25, rotate: -8 } : false}
        animate={{ opacity: 1, y: 0, rotate: -5 }}
        transition={{ delay: 0.7, duration: 0.8 }}
      >
        <span>FIELD NOTE / 001</span>
        <p>
          “What if the answer
          <br />
          was already in there?”
        </p>
        <span>
          LET’S FIND OUT. <span>↗</span>
        </span>
      </motion.div>
      <span className="studio-art-credit">
        THE THINKING COLLECTION — PLATE 01
      </span>
    </div>
  );
}

export function ReadingManifesto() {
  const { active } = useLandingAnimation();
  return (
    <motion.h2
      className="studio-manifesto"
      aria-label="The world has enough information. What it needs is a little more understanding."
      initial={active ? "hidden" : false}
      whileInView="visible"
      viewport={{ once: true, amount: 0.5 }}
      variants={{
        hidden: {},
        visible: { transition: { staggerChildren: 0.06 } },
      }}
    >
      {[
        "The world has",
        "enough information.",
        "What it needs is",
        "a little more",
        "understanding.",
      ].map((text, index) => (
        <motion.span
          key={text}
          variants={{
            hidden: { opacity: 0.15, y: 12 },
            visible: { opacity: 1, y: 0, transition: { duration: 0.7 } },
          }}
          className={index === 4 ? "manifesto-emphasis" : ""}
        >
          {text}{" "}
        </motion.span>
      ))}
    </motion.h2>
  );
}
