import Link from "next/link";

export function Emblem({ className = "" }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 80 80"
      fill="none"
      aria-hidden="true"
    >
      {[0, 45, 90, 135].map((angle) => (
        <ellipse
          key={angle}
          cx="40"
          cy="40"
          rx="15"
          ry="35"
          stroke="currentColor"
          strokeWidth="1.5"
          transform={`rotate(${angle} 40 40)`}
        />
      ))}
      <circle cx="40" cy="40" r="5" fill="currentColor" />
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
