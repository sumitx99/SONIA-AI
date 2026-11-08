const IMAGE_EXTENSIONS = new Set([
  "apng", "avif", "bmp", "gif", "heic", "heif", "ico", "jfif", "jif",
  "jpe", "jpeg", "jpg", "jxl", "png", "svg", "tif", "tiff", "webp",
]);

/** Recognize direct image-file URLs without restricting the host. */
export function isImageUrl(value: string | undefined): value is string {
  if (!value) return false;
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" && url.protocol !== "http:") return false;
    const extension = url.pathname.split("/").pop()?.match(/\.([a-z0-9]+)$/i)?.[1]?.toLowerCase();
    return !!extension && IMAGE_EXTENSIONS.has(extension);
  } catch {
    return false;
  }
}
