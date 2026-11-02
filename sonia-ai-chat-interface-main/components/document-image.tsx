"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import {
  ChevronLeft, ChevronRight, ExternalLink, FileText, ImageOff, Maximize2, RotateCw, X, ZoomIn, ZoomOut,
} from "lucide-react";
import { refreshDocumentImage, type ImageAttachment } from "@/lib/api";
import styles from "./document-image.module.css";

// Presigned R2 links expire; renew a little before the deadline so an open view never breaks.
const EXPIRY_MARGIN_MS = 30_000;

type SignedImage = { attachment: ImageAttachment; signedAt: number };
type Refresh = (index: number) => Promise<boolean>;

const labelOf = (image: ImageAttachment) => `Page ${image.page_number} · Image ${image.image_number}`;

function useSignedImages(images: ImageAttachment[]) {
  const [items, setItems] = useState<SignedImage[]>(() =>
    images.map((attachment) => ({ attachment, signedAt: Date.now() })));
  const itemsRef = useRef(items);
  itemsRef.current = items;
  const imagesRef = useRef(images);
  imagesRef.current = images;
  const inFlight = useRef(new Map<number, Promise<boolean>>());

  // Concurrent callers (card + lightbox) share one request per image.
  const refresh = useCallback<Refresh>((index) => {
    const running = inFlight.current.get(index);
    if (running) return running;
    const { document_id, image_id } = imagesRef.current[index];
    const request = refreshDocumentImage(document_id, image_id)
      .then((attachment) => {
        setItems((previous) => previous.map((item, i) =>
          i === index ? { attachment, signedAt: Date.now() } : item));
        return true;
      })
      .catch(() => false)
      .finally(() => inFlight.current.delete(index));
    inFlight.current.set(index, request);
    return request;
  }, []);

  const ensureFresh = useCallback((index: number) => {
    const item = itemsRef.current[index];
    if (item && Date.now() - item.signedAt > item.attachment.url_expires_in * 1000 - EXPIRY_MARGIN_MS) {
      void refresh(index);
    }
  }, [refresh]);

  return { items, refresh, ensureFresh };
}

// Keeps the image's own aspect ratio reserved while it loads, and never upscales small images.
function frameStyle(image: ImageAttachment): CSSProperties | undefined {
  if (!(image.width > 0 && image.height > 0)) return undefined;
  return { aspectRatio: `${image.width} / ${image.height}`, maxWidth: `min(100%, ${image.width}px)` };
}

function ImageCard({ item, index, compact, onOpen, onRefresh }: {
  item: SignedImage; index: number; compact: boolean;
  onOpen: (index: number) => void; onRefresh: Refresh;
}) {
  const { attachment } = item;
  const label = labelOf(attachment);
  // Status is keyed by URL, so a renewed link starts loading again without an effect.
  const [loadedUrl, setLoadedUrl] = useState<string | null>(null);
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const status = failedUrl === attachment.url ? "failed" : loadedUrl === attachment.url ? "ready" : "loading";
  const [reloading, setReloading] = useState(false);
  const retried = useRef(false);

  async function recover(manual: boolean) {
    const url = attachment.url;
    if (!manual && retried.current) return setFailedUrl(url);
    retried.current = true;
    setReloading(true);
    const renewed = await onRefresh(index);
    setReloading(false);
    if (!renewed) setFailedUrl(url);
    else if (manual) setFailedUrl(null);
  }

  return (
    <figure className={`${styles.figure} ${compact ? styles.compact : ""}`}>
      <div className={styles.mat}>
        {status === "failed" ? (
          <div className={styles.unavailable} role="alert">
            <ImageOff size={22} aria-hidden />
            <span>This image couldn’t be loaded. Its link may have expired.</span>
            <button type="button" onClick={() => recover(true)} disabled={reloading}>
              <RotateCw size={14} aria-hidden className={reloading ? styles.spin : undefined} />
              {reloading ? "Reloading…" : "Try again"}
            </button>
          </div>
        ) : (
          <button type="button" className={styles.frame} style={frameStyle(attachment)}
            onClick={() => onOpen(index)} aria-label={`Enlarge ${label}`}>
            {status === "loading" && <span className={styles.skeleton} aria-hidden />}
            {/* R2 links are temporary; a plain image avoids proxying private URLs through Next.js. */}
            <img src={attachment.url} alt={label} width={attachment.width} height={attachment.height}
              loading="lazy" decoding="async" referrerPolicy="no-referrer"
              data-ready={status === "ready"}
              onLoad={() => { retried.current = false; setLoadedUrl(attachment.url); }}
              onError={() => recover(false)} />
            <span className={styles.enlarge} aria-hidden><Maximize2 size={14} /></span>
          </button>
        )}
      </div>
      <figcaption className={styles.caption}>
        <strong>{label}</strong>
        {attachment.heading_path.length > 0 && (
          <span className={styles.heading}>{attachment.heading_path.join(" › ")}</span>
        )}
        {attachment.source_url && (
          <a href={attachment.source_url} target="_blank" rel="noreferrer">
            <FileText size={13} aria-hidden /> Open source page
          </a>
        )}
      </figcaption>
      <details className={styles.context}>
        <summary>Text around this image</summary>
        {(["before", "after"] as const).map((side) => (
          <div key={side}>
            <strong>{side === "before" ? "Before the image" : "After the image"}</strong>
            {attachment[`${side}_context`].length ? attachment[`${side}_context`].map((block, i) => (
              <div key={`${block.page_number}-${block.block_number}-${i}`}>
                <small>Page {block.page_number}</small>
                <p>{block.text}</p>
              </div>
            )) : <p>No surrounding text was extracted on this side.</p>}
          </div>
        ))}
        <small>Image position (PDF points): {attachment.bbox.map((value) => value.toFixed(1)).join(", ")}.
          Surrounding text follows the detected reading order.</small>
      </details>
    </figure>
  );
}

function Lightbox({ items, index, onIndex, onClose, onRefresh, ensureFresh }: {
  items: SignedImage[]; index: number | null; onIndex: (index: number) => void; onClose: () => void;
  onRefresh: Refresh; ensureFresh: (index: number) => void;
}) {
  const [zoomed, setZoomed] = useState(false);
  const [failed, setFailed] = useState(false);
  const retried = useRef(false);
  const current = index === null ? null : items[index];
  const count = items.length;

  useEffect(() => {
    if (index === null) return;
    setZoomed(false);
    setFailed(false);
    retried.current = false;
    ensureFresh(index);
  }, [index, ensureFresh]);

  const step = (delta: number) => index !== null && count > 1 && onIndex((index + delta + count) % count);

  async function recover() {
    if (index === null || retried.current) return setFailed(true);
    retried.current = true;
    if (!(await onRefresh(index))) setFailed(true);
  }

  return (
    <Dialog.Root open={current !== null} onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className={styles.overlay} />
        <Dialog.Content className={styles.lightbox} aria-describedby={undefined}
          // Focus the dialog itself so arrow keys work at once without a focus ring on a toolbar button.
          onOpenAutoFocus={(event) => { event.preventDefault(); (event.currentTarget as HTMLElement).focus(); }}
          onKeyDown={(event) => {
            if (event.key === "ArrowLeft") step(-1);
            if (event.key === "ArrowRight") step(1);
          }}>
          {current && (
            <>
              <header className={styles.toolbar}>
                <div className={styles.title}>
                  <Dialog.Title>{labelOf(current.attachment)}</Dialog.Title>
                  {current.attachment.heading_path.length > 0 && (
                    <span>{current.attachment.heading_path.join(" › ")}</span>
                  )}
                </div>
                {count > 1 && <span className={styles.counter}>{index! + 1} / {count}</span>}
                <button type="button" onClick={() => setZoomed((z) => !z)}
                  aria-label={zoomed ? "Fit to screen" : "View actual size"} aria-pressed={zoomed}>
                  {zoomed ? <ZoomOut size={18} /> : <ZoomIn size={18} />}
                </button>
                <a href={current.attachment.url} target="_blank" rel="noreferrer" aria-label="Open original image">
                  <ExternalLink size={18} />
                </a>
                {current.attachment.source_url && (
                  <a href={current.attachment.source_url} target="_blank" rel="noreferrer"
                    aria-label="Open source page">
                    <FileText size={18} />
                  </a>
                )}
                <Dialog.Close aria-label="Close"><X size={20} /></Dialog.Close>
              </header>

              <div className={`${styles.stage} ${zoomed ? styles.zoomed : ""}`}>
                {failed ? (
                  <div className={styles.stageError} role="alert">
                    <ImageOff size={28} aria-hidden />
                    <span>This image couldn’t be loaded.</span>
                  </div>
                ) : (
                  <img key={current.attachment.url} src={current.attachment.url}
                    alt={labelOf(current.attachment)} referrerPolicy="no-referrer"
                    onClick={() => setZoomed((z) => !z)} onError={recover} />
                )}
              </div>

              {count > 1 && (
                <>
                  <button type="button" className={`${styles.nav} ${styles.prev}`} onClick={() => step(-1)}
                    aria-label="Previous image"><ChevronLeft size={24} /></button>
                  <button type="button" className={`${styles.nav} ${styles.next}`} onClick={() => step(1)}
                    aria-label="Next image"><ChevronRight size={24} /></button>
                </>
              )}
            </>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export function DocumentImageGallery({ images }: { images: ImageAttachment[] }) {
  const { items, refresh, ensureFresh } = useSignedImages(images);
  const [openIndex, setOpenIndex] = useState<number | null>(null);
  if (!items.length) return null;
  const compact = items.length > 1;

  return (
    <>
      <div className={compact ? styles.grid : undefined}>
        {items.map((item, index) => (
          <ImageCard key={images[index].image_id} item={item} index={index} compact={compact}
            onOpen={setOpenIndex} onRefresh={refresh} />
        ))}
      </div>
      <Lightbox items={items} index={openIndex} onIndex={setOpenIndex} onClose={() => setOpenIndex(null)}
        onRefresh={refresh} ensureFresh={ensureFresh} />
    </>
  );
}

export function DocumentImage({ image }: { image: ImageAttachment }) {
  const images = useMemo(() => [image], [image]);
  return <DocumentImageGallery images={images} />;
}
