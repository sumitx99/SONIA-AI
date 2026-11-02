"use client";

import {
  createContext,
  useContext,
  useState,
  type ReactNode,
  type PointerEvent,
} from "react";
import {
  motion,
  MotionConfig,
  useReducedMotion,
  useSpring,
} from "motion/react";
import { Pause, Play } from "lucide-react";

const AnimationContext = createContext({
  active: true,
  paused: false,
  toggle: () => {},
});

export function useLandingAnimation() {
  return useContext(AnimationContext);
}

export function LandingMotion({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  const reduced = useReducedMotion();
  const [paused, setPaused] = useState(false);
  const active = !reduced && !paused;
  return (
    <AnimationContext.Provider
      value={{
        active,
        paused: paused || !!reduced,
        toggle: () => setPaused((value) => !value),
      }}
    >
      <MotionConfig reducedMotion="user">
        <div
          className={`editorial-site ${className}`}
          data-motion={active ? "running" : "paused"}
        >
          {children}
        </div>
      </MotionConfig>
    </AnimationContext.Provider>
  );
}

export function MotionToggle() {
  const { paused, toggle } = useContext(AnimationContext);
  const reduced = useReducedMotion();
  return (
    <button
      className="motion-toggle"
      onClick={toggle}
      disabled={!!reduced}
      aria-label={
        reduced
          ? "Motion reduced by system preference"
          : paused
            ? "Play animations"
            : "Pause animations"
      }
      title={
        reduced
          ? "Motion reduced by system preference"
          : paused
            ? "Play animations"
            : "Pause animations"
      }
      aria-pressed={paused}
    >
      {paused ? <Play size={15} /> : <Pause size={15} />}
    </button>
  );
}

export function HeroHeading() {
  const { active } = useContext(AnimationContext);
  return (
    <motion.h1
      className="animated-heading"
      initial={active ? "hidden" : false}
      animate="visible"
      variants={{
        hidden: {},
        visible: { transition: { staggerChildren: 0.13, delayChildren: 0.12 } },
      }}
    >
      {["The art of", "understanding."].map((line, index) => (
        <span className="heading-line" key={line}>
          <motion.span
            variants={{
              hidden: { y: "110%", rotate: 3, opacity: 0 },
              visible: {
                y: "0%",
                rotate: 0,
                opacity: 1,
                transition: { duration: 0.9, ease: [0.22, 1, 0.36, 1] },
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

export function HeroScene({ children }: { children: ReactNode }) {
  const { active } = useContext(AnimationContext);
  const rotateX = useSpring(0, { stiffness: 100, damping: 24 });
  const rotateY = useSpring(0, { stiffness: 100, damping: 24 });
  function move(event: PointerEvent<HTMLDivElement>) {
    if (!active || event.pointerType !== "mouse") return;
    const bounds = event.currentTarget.getBoundingClientRect();
    rotateX.set(-((event.clientY - bounds.top) / bounds.height - 0.5) * 8);
    rotateY.set(((event.clientX - bounds.left) / bounds.width - 0.5) * 10);
  }
  return (
    <motion.div
      className="hero-art-scene"
      onPointerMove={move}
      onPointerLeave={() => {
        rotateX.set(0);
        rotateY.set(0);
      }}
      style={{
        rotateX: active ? rotateX : 0,
        rotateY: active ? rotateY : 0,
        transformPerspective: 1000,
      }}
    >
      {children}
    </motion.div>
  );
}
