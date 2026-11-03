import { ImageResponse } from "next/og";

// The folded-page Sonia S, matching the SVG favicon and in-app wordmark.
export const size = { width: 180, height: 180 };
export const contentType = "image/png";

export default function AppleIcon() {
  return new ImageResponse(
    (
      <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center",
                    justifyContent: "center", background: "#292826" }}>
        <svg width="140" height="140" viewBox="0 0 80 80" fill="#cdccca">
          <path d="M20 13H66L50 29H36L20 45V13Z" />
          <path d="M60 67H14L30 51H44L60 35V67Z" />
        </svg>
      </div>
    ),
    size,
  );
}
