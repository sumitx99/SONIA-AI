"use client";

import { useId } from "react";

// Illustrations for the three landing method cards. Drawn on a 400×300 canvas in the
// Sonia palette; their motion lives in landing.css (.art-*), and stops for reduced motion.

const INK = "#302a23";
const LINE = "#cdbfa6";
const PAPER = "#fffaf1";
const RED = "#b5533a";

function Backdrop({ id }: { id: string }) {
  return (
    <>
      <defs>
        <radialGradient id={`${id}-bg`} cx="35%" cy="25%" r="90%">
          <stop offset="0" stopColor="#f6efe2" />
          <stop offset="1" stopColor="#e4d6bd" />
        </radialGradient>
        <filter id={`${id}-shadow`} x="-20%" y="-20%" width="140%" height="150%">
          <feDropShadow dx="0" dy="6" stdDeviation="7" floodColor="#5a4632" floodOpacity="0.18" />
        </filter>
      </defs>
      <rect width="400" height="300" fill={`url(#${id}-bg)`} />
    </>
  );
}

/** Text lines on a sheet: x/y of the first line, widths of each. */
function Lines({ x, y, widths, gap = 13, color = LINE }: { x: number; y: number; widths: number[]; gap?: number; color?: string }) {
  return (
    <g stroke={color} strokeWidth="4" strokeLinecap="round">
      {widths.map((width, index) => (
        <line key={index} x1={x} x2={x + width} y1={y + index * gap} y2={y + index * gap} />
      ))}
    </g>
  );
}

function Sheet({ width = 150, height = 190, fold = true }: { width?: number; height?: number; fold?: boolean }) {
  const corner = 26;
  return (
    <>
      <path d={`M0 0 H${width - (fold ? corner : 0)} L${width} ${fold ? corner : 0} V${height} H0 Z`}
        fill={PAPER} stroke="#d9ccb5" strokeWidth="1.2" />
      {fold && <path d={`M${width - corner} 0 V${corner} H${width}`} fill="#efe4d0" stroke="#d9ccb5" strokeWidth="1.2" />}
    </>
  );
}

export function PagesArt() {
  const id = useId().replace(/:/g, "");
  return (
    <svg viewBox="0 0 400 300" preserveAspectRatio="xMidYMid slice" className="method-art art-pages" role="img"
      aria-label="A stack of documents, with a new page settling on top">
      <Backdrop id={id} />
      <g filter={`url(#${id}-shadow)`}>
        <g transform="translate(108 70) rotate(-9)"><Sheet fold={false} /></g>
        <g transform="translate(122 62) rotate(-3)">
          <Sheet fold={false} />
          <Lines x={18} y={30} widths={[90, 110, 70]} />
        </g>
        <g transform="translate(140 58) rotate(4)">
          <Sheet />
          <rect x="16" y="20" width="34" height="16" rx="3" fill={RED} />
          <text x="33" y="32" textAnchor="middle" fontSize="10" fontFamily="ui-monospace, monospace" fill={PAPER}>PDF</text>
          <Lines x={16} y={56} widths={[112, 96, 118, 80, 104, 60]} />
        </g>
        {/* The page being brought in: drifts down and settles on the stack. */}
        <g className="art-pages-incoming">
          <g transform="translate(186 34) rotate(12)">
            <Sheet width={120} height={150} />
            <Lines x={14} y={36} widths={[70, 86, 60, 80]} color="#d8c8ad" />
            <circle cx="22" cy="118" r="6" fill="none" stroke={RED} strokeWidth="2" />
          </g>
        </g>
      </g>
      <path d="M318 214 q10 -18 0 -36" stroke={RED} strokeWidth="2.5" fill="none" strokeLinecap="round" className="art-pages-arrow" />
      <path d="M312 186 l6 -8 l8 6" stroke={RED} strokeWidth="2.5" fill="none" strokeLinecap="round" strokeLinejoin="round" className="art-pages-arrow" />
    </svg>
  );
}

export function ThreadArt() {
  const id = useId().replace(/:/g, "");
  const notes = [
    { x: 44, y: 56, r: -6, lines: [56, 40] },
    { x: 238, y: 40, r: 5, lines: [62, 46] },
    { x: 150, y: 168, r: -3, lines: [50, 64] },
    { x: 290, y: 176, r: 7, lines: [48, 36] },
  ];
  return (
    <svg viewBox="0 0 400 300" preserveAspectRatio="xMidYMid slice" className="method-art art-thread" role="img"
      aria-label="Notes joined one to the next by a red thread">
      <Backdrop id={id} />
      <g filter={`url(#${id}-shadow)`}>
        {notes.map((note, index) => (
          <g key={index} transform={`translate(${note.x} ${note.y}) rotate(${note.r})`}>
            <rect width="86" height="68" rx="4" fill={PAPER} stroke="#d9ccb5" strokeWidth="1.2" />
            <Lines x={12} y={22} widths={note.lines} gap={14} />
            <circle cx="43" cy="0" r="5" fill={RED} />
          </g>
        ))}
      </g>
      {/* The thread runs pin to pin and draws itself; a loose end trails off. */}
      <path className="art-thread-line" pathLength={1}
        d="M87 52 C 150 20, 200 110, 281 40 C 320 10, 250 150, 193 166 C 150 178, 300 230, 333 172 C 350 140, 380 250, 360 280"
        fill="none" stroke={RED} strokeWidth="2.6" strokeLinecap="round" />
      <circle className="art-thread-tip" r="4.5" fill={RED}>
        <animateMotion dur="5s" repeatCount="indefinite" keyPoints="0;1;1" keyTimes="0;0.7;1" calcMode="linear"
          path="M87 52 C 150 20, 200 110, 281 40 C 320 10, 250 150, 193 166 C 150 178, 300 230, 333 172 C 350 140, 380 250, 360 280" />
      </circle>
      {/* Position on the outer group: the CSS bob animation owns the inner group's transform. */}
      <g transform="translate(40 196)">
        <g className="art-thread-ask">
          <rect width="74" height="46" rx="23" fill={INK} />
          <text x="37" y="31" textAnchor="middle" fontSize="24" fontFamily="Georgia, serif" fontStyle="italic" fill={PAPER}>?</text>
        </g>
      </g>
    </svg>
  );
}

export function ClarityArt() {
  const id = useId().replace(/:/g, "");
  const widths = [210, 180, 220, 160, 200, 190, 120];
  const page = (
    <>
      <text x="96" y="66" fontSize="20" fontFamily="Georgia, serif" fill={INK}>The key idea</text>
      <g stroke={INK} strokeWidth="5" strokeLinecap="round" opacity="0.75">
        {widths.map((width, index) => (
          <line key={index} x1="96" x2={96 + width} y1={96 + index * 22} y2={96 + index * 22} />
        ))}
      </g>
      <rect x="94" y="132" width="150" height="16" rx="3" fill={RED} opacity="0.25" />
    </>
  );
  return (
    <svg viewBox="0 0 400 300" preserveAspectRatio="xMidYMid slice" className="method-art art-clarity" role="img"
      aria-label="A lens moving over a blurred page, bringing the words into focus">
      <Backdrop id={id} />
      <defs>
        <filter id={`${id}-blur`}><feGaussianBlur stdDeviation="4" /></filter>
        <clipPath id={`${id}-lens`}>
          <circle className="art-clarity-lens-clip" cx="190" cy="120" r="58" />
        </clipPath>
      </defs>
      <g filter={`url(#${id}-shadow)`}>
        <rect x="70" y="30" width="260" height="240" rx="6" fill={PAPER} stroke="#d9ccb5" strokeWidth="1.2" />
      </g>
      {/* Outside the lens the page is soft; inside it, sharp. */}
      <g filter={`url(#${id}-blur)`} opacity="0.55">{page}</g>
      <g clipPath={`url(#${id}-lens)`}>
        <rect x="70" y="30" width="260" height="240" fill={PAPER} />
        {page}
      </g>
      <g className="art-clarity-lens">
        <circle cx="190" cy="120" r="58" fill="none" stroke={INK} strokeWidth="7" />
        <circle cx="190" cy="120" r="58" fill="none" stroke="#fff" strokeWidth="1.5" opacity="0.6" />
        <path d="M232 162 L282 212" stroke={INK} strokeWidth="14" strokeLinecap="round" />
        <path d="M164 84 a40 40 0 0 1 30 -10" stroke="#fff" strokeWidth="4" strokeLinecap="round" fill="none" opacity="0.8" />
      </g>
      <g className="art-clarity-spark" fill={RED}>
        <path d="M318 58 l4 10 l10 4 l-10 4 l-4 10 l-4 -10 l-10 -4 l10 -4 z" />
      </g>
    </svg>
  );
}
