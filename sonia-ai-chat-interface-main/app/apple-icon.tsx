import { ImageResponse } from "next/og";

// Home-screen icon for iOS (it does not use SVG favicons): the Sonia atom on the hero dark.
export const size = { width: 180, height: 180 };
export const contentType = "image/png";

export default function AppleIcon() {
  return new ImageResponse(
    (
      <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center",
                    justifyContent: "center", background: "#201f19" }}>
        <svg width="140" height="140" viewBox="0 0 64 64">
          {[0, 45, 90, 135].map((angle) => (
            <ellipse key={angle} cx="32" cy="32" rx="9" ry="24" fill="none" stroke="#d2b68d"
              strokeWidth="2.4" transform={`rotate(${angle} 32 32)`} />
          ))}
          <circle cx="32" cy="32" r="4.5" fill="#f0eadc" />
        </svg>
      </div>
    ),
    size,
  );
}
