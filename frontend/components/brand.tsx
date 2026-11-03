import Link from "next/link";

export function Emblem({ className = "" }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 80 80"
      fill="none"
      aria-hidden="true"
    >
      <path className="sonia-fold sonia-fold-top" d="M20 13H66L50 29H36L20 45V13Z" fill="currentColor" />
      <path className="sonia-fold sonia-fold-bottom" d="M60 67H14L30 51H44L60 35V67Z" fill="currentColor" />
      <path className="sonia-fold-seam" d="M25 39L55 41" stroke="currentColor" strokeWidth="1" opacity="0.35" />
    </svg>
  );
}

export function Brand({ light = false }: { light?: boolean }) {
  return (
    <Link
      href="/"
      className={`brand ${light ? "brand-light" : ""}`}
      aria-label="Sonia home"
    >
      <Emblem />
      <span>
        sonia<span className="brand-period">.</span>
      </span>
    </Link>
  );
}
