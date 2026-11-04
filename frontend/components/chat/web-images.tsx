"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ExternalLink, Globe, ImageOff, Loader2, RotateCw } from "lucide-react";
import { refreshWebImage, handleApiError, type WebImage } from "@/lib/api";
import styles from "./web-images.module.css";

function ImageCard({ image }: { image: WebImage }) {
  const [current, setCurrent] = useState(image);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const mounted = useRef(true);
  const inFlight = useRef(false);
  const retried = useRef(false);
  const renew = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    try {
      const fresh = await refreshWebImage(image.image_id);
      if (mounted.current) { setCurrent(fresh); setError(""); }
    } catch (failure) { if (mounted.current) setError(handleApiError(failure)); }
    finally { inFlight.current = false; if (mounted.current) setBusy(false); }
  }, [image.image_id]);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => { setCurrent(image); }, [image]);
  useEffect(() => {
    if (!current.url) { void renew(); return; }
    const timer = window.setTimeout(() => { void renew(); }, Math.max(1, current.url_expires_in - 30) * 1000);
    return () => window.clearTimeout(timer);
  }, [current.url, current.url_expires_in, renew]);
  return <figure className={styles.card}>
    <div className={styles.preview}>
      {error ? <div className={styles.error} role="alert"><ImageOff size={22} /><p>{error}</p>
        <button type="button" disabled={busy} onClick={() => { retried.current = false; void renew(); }}><RotateCw size={14} />Try again</button></div>
        : current.url ? <a href={current.source_url} target="_blank" rel="noopener noreferrer" aria-label={`View source: ${current.title}`}>
          <img src={current.url} alt={current.title} width={current.width} height={current.height} loading="lazy" decoding="async" referrerPolicy="no-referrer"
            onLoad={() => setError("")} onError={() => {
              if (!retried.current) { retried.current = true; void renew(); }
              else setError("This image couldn’t be loaded. Try refreshing its link.");
            }} />
        </a> : <span className={styles.loading}><Loader2 size={20} className="animate-spin" />Loading image…</span>}
    </div>
    <figcaption className={styles.caption}>
      <span className={styles.eyebrow}><Globe size={12} />Web image · {current.provider}</span>
      <strong>{current.title}</strong>
      {current.author && <span className={styles.author}>By {current.author}</span>}
      <div className={styles.links}>
        <a href={current.source_url} target="_blank" rel="noopener noreferrer"><ExternalLink size={12} />Source</a>
        <a href={current.license_url} target="_blank" rel="noopener noreferrer">{current.license}</a>
      </div>
      <small>{current.preview_note}</small>
    </figcaption>
  </figure>;
}

export function WebImageGallery({ images }: { images: WebImage[] }) {
  return <section className={styles.gallery} aria-label="Web images and their sources">
    {images.map(image => <ImageCard key={image.image_id} image={image} />)}
  </section>;
}
