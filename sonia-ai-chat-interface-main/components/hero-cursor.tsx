"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useLandingAnimation } from "@/components/landing-motion";

/**
 * A custom cursor for the hero: a small square that, over the target text, opens into a
 * selection box. It uses mix-blend-mode: difference, so everything beneath it inverts.
 * Mouse only; touch, reduced motion and the page's pause toggle keep the normal cursor.
 */
export function HeroCursor({ target }: { target: string }) {
  const anchor = useRef<HTMLSpanElement>(null);
  const cursor = useRef<HTMLDivElement>(null);
  const { active } = useLandingAnimation();
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);

  useEffect(() => {
    const section = anchor.current?.parentElement;
    const element = cursor.current;
    if (!active || !section || !element) return;
    if (!window.matchMedia("(hover: hover) and (pointer: fine)").matches) return;

    const heading = section.querySelector(target);
    // The headline's real text boxes (not its full-width block), so the box opens on the words.
    const textBoxes = () => {
      if (!heading) return [];
      const boxes: DOMRect[] = [];
      const walker = document.createTreeWalker(heading, NodeFilter.SHOW_TEXT);
      const range = document.createRange();
      for (let node = walker.nextNode(); node; node = walker.nextNode()) {
        range.selectNodeContents(node);
        boxes.push(...range.getClientRects());
      }
      return boxes;
    };

    let frame = 0;
    let x = 0;
    let y = 0;
    const render = () => {
      frame = 0;
      element.style.transform = `translate3d(${x}px, ${y}px, 0)`;
      const over = textBoxes().some((box) =>
        x >= box.left && x <= box.right && y >= box.top && y <= box.bottom);
      element.classList.toggle("is-expanded", over);
    };
    const move = (event: PointerEvent) => {
      if (event.pointerType !== "mouse") return;
      x = event.clientX;
      y = event.clientY;
      element.classList.add("is-visible");
      frame ||= requestAnimationFrame(render);
    };
    const leave = () => element.classList.remove("is-visible", "is-expanded");

    section.classList.add("has-hero-cursor");
    section.addEventListener("pointermove", move);
    section.addEventListener("pointerleave", leave);
    // Scrolling moves the words under a still pointer.
    window.addEventListener("scroll", render, { passive: true });
    return () => {
      cancelAnimationFrame(frame);
      section.classList.remove("has-hero-cursor");
      section.removeEventListener("pointermove", move);
      section.removeEventListener("pointerleave", leave);
      window.removeEventListener("scroll", render);
      leave();
    };
  }, [active, target, mounted]);

  return (
    <>
      <span ref={anchor} hidden />
      {mounted && createPortal(
        <div ref={cursor} className="hero-cursor" aria-hidden="true">
          <div className="hero-cursor-box">
            <i className="hero-cursor-handle is-tl" />
            <i className="hero-cursor-handle is-tr" />
            <i className="hero-cursor-handle is-bl" />
            <i className="hero-cursor-handle is-br" />
            <span className="hero-cursor-label">YOU</span>
          </div>
        </div>,
        document.body,
      )}
    </>
  );
}
