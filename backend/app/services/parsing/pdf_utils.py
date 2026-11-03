"""Split parsed Markdown into sections before applying overlapping chunking."""

import re
from collections.abc import Iterator

from langchain_text_splitters import RecursiveCharacterTextSplitter


_ATX_HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)\s*$")
_SETEXT_UNDERLINE = re.compile(r"^ {0,3}(=+|-+)[ \t]*\r?$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


def _markdown_sections(text: str) -> Iterator[tuple[list[str], str]]:
    """Yield heading paths and section bodies, ignoring headings inside fences."""
    headings: list[tuple[int, str]] = []
    body: list[str] = []
    fence_char = ""
    fence_length = 0
    lines = text.splitlines(keepends=True)
    index = 0

    while index < len(lines):
        line = lines[index]
        fence = _FENCE.match(line)
        if fence_char:
            body.append(line)
            if (fence and fence.group(1)[0] == fence_char
                    and len(fence.group(1)) >= fence_length
                    and not fence.group(2).strip()):
                fence_char = ""
            index += 1
            continue
        if fence:
            fence_char = fence.group(1)[0]
            fence_length = len(fence.group(1))
            body.append(line)
            index += 1
            continue

        heading = _ATX_HEADING.match(line)
        level = 0
        title = ""
        consumed = 1
        if heading:
            level = len(heading.group(1))
            title = re.sub(r"[ \t]+#+[ \t]*$", "", heading.group(2)).strip()
        elif (line.strip() and not line.startswith(("    ", "\t"))
              and index + 1 < len(lines)):
            underline = _SETEXT_UNDERLINE.match(lines[index + 1])
            if underline:
                level = 1 if underline.group(1)[0] == "=" else 2
                title = line.strip()
                consumed = 2

        if level:
            section = "".join(body).strip()
            if section:
                yield [name for _, name in headings], section
            body = []
            while headings and headings[-1][0] >= level:
                headings.pop()
            headings.append((level, title))
        else:
            body.append(line)
        index += consumed

    section = "".join(body).strip()
    if section:
        yield [name for _, name in headings], section
    elif headings:
        # Keep a final heading searchable even if it has no body.
        yield [name for _, name in headings], ""


def chunk_text(text: str, chunk_size: int = 1000, chunk_overlap: int = 100) -> list[str]:
    """Return section-aware text chunks compatible with the existing DB pipeline.

    Sizes are characters, not tokens. ``chunk_size`` bounds each body chunk;
    the heading path is additional context prepended to every chunk. Overlap
    applies only within a section and depends on available separator boundaries.
    Documents without Markdown headings use ordinary recursive splitting.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if not 0 <= chunk_overlap < chunk_size:
        raise ValueError("chunk_overlap must be nonnegative and less than chunk_size")

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        separators=["\n\n", "\n", " ", ""],
    )
    chunks = []
    for heading_path, body in _markdown_sections(text):
        prefix = f"Section: {' > '.join(heading_path)}\n\n" if heading_path else ""
        if not body:
            chunks.append(prefix.strip())
            continue
        chunks.extend(prefix + part for part in text_splitter.split_text(body))
    return chunks
