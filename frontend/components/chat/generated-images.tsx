"use client";
import { useState } from "react";
import type { GeneratedImage } from "@/lib/api";

function GeneratedImageCard({ image }: { image: GeneratedImage }) {
  const [failed, setFailed] = useState(false);
  return <figure style={{ margin: "0.75rem 0", maxWidth: "100%" }}>
    {failed ? <a href={image.src} target="_blank" rel="noreferrer nofollow">Open generated image</a>
      : <img src={image.src} alt={image.alt || "Generated image"} loading="lazy" decoding="async"
        referrerPolicy="no-referrer" onError={() => setFailed(true)}
        style={{ display: "block", maxWidth: "100%", maxHeight: 640, objectFit: "contain", borderRadius: 8 }} />}
  </figure>;
}

export function GeneratedImageGallery({ images }: { images: GeneratedImage[] }) {
  if (!images.length) return null;
  return <section aria-label="Images returned by connected tools">
    {images.map((image, index) => <GeneratedImageCard key={`${image.src.slice(0, 80)}-${index}`} image={image} />)}
  </section>;
}
