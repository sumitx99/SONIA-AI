"""Extract image occurrences and their surrounding source text from PDFs."""

import re
import unicodedata
from collections.abc import Iterator
from uuid import uuid4

import pymupdf

from app.services.parsing.pdf_utils import _markdown_sections


def _normalized(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def extract_document_images(pdf_bytes: bytes, markdown: str = "") -> list[dict]:
    """Keep each displayed image occurrence, including repeated images.

    Neighbor text uses PyMuPDF's geometric reading order, not PDF object order.
    Bboxes and page numbers always refer to the original PDF. Heading matching
    is best effort against the Markdown; unmatched headings are left empty.
    """
    paths = {}
    for path, _ in _markdown_sections(markdown):
        for end in range(1, len(path) + 1):
            paths.setdefault(_normalized(path[end - 1]), []).append(path[:end])

    events = []
    heading_path = []
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as document:
        for page_number, page in enumerate(document, start=1):
            image_number = 0
            for order, block in enumerate(page.get_text("dict", sort=True)["blocks"]):
                location = {
                    "page_number": page_number,
                    "block_number": block.get("number", order),
                    "bbox": list(block["bbox"]),
                }
                if block["type"] == 0:
                    lines = ["".join(span["text"] for span in line["spans"])
                             for line in block["lines"]]
                    text = "\n".join(lines).strip()
                    if not text:
                        continue
                    # A PDF text block may contain both a heading and a paragraph.
                    for candidate in [text, *lines]:
                        matches = paths.get(_normalized(candidate), [])
                        unique_paths = {tuple(path) for path in matches}
                        if len(unique_paths) == 1:
                            heading_path = list(next(iter(unique_paths)))
                    events.append({"kind": "text", "text": text, **location})
                elif block["type"] == 1 and block.get("image"):
                    image_number += 1
                    # Pixels are rendered later, one image at a time (render_document_images),
                    # so a scanned PDF never holds every page's raster in memory at once.
                    events.append({
                        "kind": "image", "image_id": str(uuid4()),
                        "image_number": image_number, **location,
                        "heading_path": list(heading_path),
                        "page_size": [page.cropbox.width, page.cropbox.height],
                        "page_rotation": page.rotation,
                        "coordinate_system": "unrotated_page_points",
                        "context_order": "geometric",
                        "content_type": "image/png", "extension": "png",
                    })

    images = []
    text_events = [event for event in events if event["kind"] == "text"]
    text_index = 0
    for event in events:
        if event["kind"] == "text":
            text_index += 1
            continue
        before = text_events[max(0, text_index - 2):text_index]
        after = text_events[text_index:text_index + 2]
        event["before_context"] = [{key: value for key, value in item.items()
                                    if key != "kind"} for item in before]
        event["after_context"] = [{key: value for key, value in item.items()
                                   if key != "kind"} for item in after]
        event["text_before"] = "\n\n".join(item["text"] for item in before)
        event["text_after"] = "\n\n".join(item["text"] for item in after)
        event["search_text"] = (
            f"Image {event['image_number']} on page {event['page_number']}\n"
            f"Section: {' > '.join(event['heading_path'])}\n"
            f"Text before image:\n{event['text_before'][-1500:]}\n"
            f"Text after image:\n{event['text_after'][:1500]}"
        )
        event.pop("kind")
        images.append(event)
    return images


def render_document_images(pdf_bytes: bytes, images: list[dict]) -> Iterator[tuple[dict, bytes]]:
    """Yield (image, PNG bytes) one at a time, setting each image's width and height.

    Each PNG is the exact visible region of the occurrence (transparency and masks applied,
    no hidden background). Callers should let each PNG go before taking the next.
    """
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as document:
        for image in images:
            page = document[image["page_number"] - 1]
            clip = pymupdf.Rect(image["bbox"]) * page.rotation_matrix
            # Bound raster memory on small servers, even for poster-sized PDFs.
            scale = min(2.0, 1600 / max(clip.width, clip.height, 1))
            pixmap = page.get_pixmap(clip=clip, matrix=pymupdf.Matrix(scale, scale), alpha=False)
            image["width"], image["height"] = pixmap.width, pixmap.height
            data = pixmap.tobytes("png")
            del pixmap
            # MuPDF caches each decoded source image (a scanned page is often 30+ MB raw) and
            # never reuses it for the next occurrence's page; empty the cache so memory stays flat.
            pymupdf.TOOLS.store_shrink(100)
            yield image, data


_IMAGE_WORDS =r"image|images|img|figure|figures|fig|diagram|diagrams|photo|photos|picture|pictures|screenshot|screenshots|illustration|illustrations|चित्र|तस्वीर|फोटो|डायग्राम|इमेज"


def wants_images(query: str) -> bool:
    return bool(re.search(rf"(?<!\w)(?:{_IMAGE_WORDS})(?!\w)", query, re.IGNORECASE))


def requested_image_location(query: str) -> tuple[int | None, int | None]:
    """Honor explicit page and per-page image numbers instead of nearest matches."""
    page = re.search(r"(?:page|pg\.?|पेज|पृष्ठ)\s*(?:no\.?\s*)?[#:]?\s*(\d+)", query, re.I)
    if not page:
        page = re.search(r"(\d+)\s*(?:page|पेज|पृष्ठ)(?!\w)", query, re.I)
    image = re.search(rf"(?<!\w)(?:{_IMAGE_WORDS})\s*(?:no\.?\s*)?[#:]?\s*(\d+)", query, re.I)
    if not image:
        image = re.search(rf"(\d+)(?:st|nd|rd|th)?\s+(?:{_IMAGE_WORDS})(?!\w)", query, re.I)
    image_number = int(image.group(1)) if image else None
    if image_number is None:
        ordinals = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
                    "pehli": 1, "pehla": 1, "dusri": 2, "doosri": 2,
                    "dusra": 2, "teesri": 3, "पहली": 1, "दूसरी": 2, "तीसरी": 3}
        ordinal = re.search(rf"(?<!\w)({'|'.join(ordinals)})\s+(?:{_IMAGE_WORDS})(?!\w)", query, re.I)
        if ordinal:
            image_number = ordinals[ordinal.group(1).casefold()]
    return (int(page.group(1)) if page else None,
            image_number)
