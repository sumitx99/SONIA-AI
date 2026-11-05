"""Checks an answer's inline citations against the sources it cites, without another model call.

The model ends its answer with a ```citations block: [{"n", "source", "quote"}]. Each quote is
looked up in the cited source's own text: a document passage, a tool result, or a web page the
answer actually used (pages the search already read, otherwise fetched safely). Only what the
source really says is marked verified; unknown sources are never linked.
"""
import json
import logging
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor

from app.services.source_reader import read_source
from app.services.web_activity import safe_url

logger = logging.getLogger(__name__)
MARKER = "SONIA_DOCUMENT_EVIDENCE\n"
MAX_CITATIONS = 40
MAX_QUOTE_WORDS = 25
MAX_FETCHES = 6
_WIDE_MARKER = re.compile(r"【(\d{1,2})】")
_BLOCK = re.compile(r"\n*```citations[^\n]*\n(.*?)(?:\n```[^\n]*|\Z)", re.S)
_ANSWER_URL = re.compile(r"""https?://[^\s<>()\[\]"'`*]+""", re.IGNORECASE)


def document_evidence(context):
    if not context.startswith(MARKER):
        return []
    try:
        payload, _ = json.JSONDecoder().raw_decode(context[len(MARKER):])
        return [item for item in payload.get("sources", []) if item.get("kind") == "document"
                and item.get("document_id") and item.get("chunk_id") and item.get("text")]
    except (ValueError, TypeError, AttributeError):
        return []


def split_citations(answer: str) -> tuple[str, list]:
    """The answer without its citations block, and the block's entries."""
    match = _BLOCK.search(answer)
    if not match:
        return answer.strip(), []
    body = (answer[:match.start()] + answer[match.end():]).strip()
    try:
        entries = json.loads(match.group(1))
    except ValueError:
        entries = []
    return body, entries if isinstance(entries, list) else []


def _normalized(text: str) -> str:
    # Same characters, different typography ("smart" quotes, dashes, odd spaces) still match.
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"}))
    return " ".join(text.casefold().split())


def _url_key(url: str) -> str:
    # Models sometimes type a source URL with typographic dashes (e.g. U+2011 in "sk‑world"),
    # which browsers resolve to a different host. Compare URLs with every dash as "-".
    url = "".join("-" if unicodedata.category(ch) == "Pd" else ch for ch in unicodedata.normalize("NFKC", url))
    return url.rstrip(".,;:!?").rstrip("/")


def _restore_source_urls(body: str, known) -> str:
    """Rewrites URLs that only differ from a known source in typography to that exact source."""
    exact = {_url_key(url): url for url in known}

    def restore(match):
        written = match.group()
        trimmed = written.rstrip(".,;:!?")
        url = exact.get(_url_key(trimmed))
        return url + written[len(trimmed):] if url and url != trimmed else written
    return _ANSWER_URL.sub(restore, body) if exact else body


def _fetch(url: str):
    try:
        return read_source(url)
    except Exception:
        logger.info("A cited page could not be read for verification")
        return ""


def check_citations(answer: str, context: str, web_sources=(), evidence=()) -> tuple[str, list[dict]]:
    """Splits off the citations block and checks every quote against its source.

    `web_sources` are the pages the answer was allowed to use ({"url", "title"}); `evidence`
    holds texts already in hand: tool results ({"id", "kind": "tool"}) and pages a search read
    ({"url", "kind": "web"}). Returns the answer body and one citation per number.
    """
    body, entries = split_citations(answer)
    # gpt-oss models sometimes write markers as 【1】; the chat renders [1].
    body = _WIDE_MARKER.sub(r"[\1]", body)
    documents = {item["id"]: item for item in document_evidence(context)}
    tools = {item["id"]: item for item in evidence if item.get("kind") == "tool" and item.get("id")}
    pages = {item["url"]: item for item in evidence if item.get("kind") == "web" and safe_url(item.get("url"))}
    allowed = {source["url"]: source for source in web_sources if safe_url(source.get("url"))}
    allowed.update(pages)
    body = _restore_source_urls(body, allowed)
    canonical = {_url_key(url): url for url in allowed}
    for entry in entries:
        if isinstance(entry, dict) and isinstance(entry.get("source"), str) and entry["source"] not in allowed:
            entry["source"] = canonical.get(_url_key(entry["source"]), entry["source"])

    cited = [entry for entry in entries[:MAX_CITATIONS] if isinstance(entry, dict)]
    to_fetch = list(dict.fromkeys(entry.get("source") for entry in cited
                                  if entry.get("source") in allowed and entry.get("source") not in pages))[:MAX_FETCHES]
    if to_fetch:
        with ThreadPoolExecutor(max_workers=4) as workers:
            for url, text in zip(to_fetch, workers.map(_fetch, to_fetch)):
                pages[url] = {"url": url, "title": allowed[url].get("title") or url, "text": text}

    citations, numbers = [], set()
    for entry in cited:
        number, source, quote = entry.get("n"), entry.get("source"), entry.get("quote")
        if not isinstance(number, int) or not 0 < number < 100 or number in numbers:
            continue
        if not isinstance(source, str) or not isinstance(quote, str) or not quote.strip():
            continue
        numbers.add(number)
        quote = " ".join(quote.split()[:MAX_QUOTE_WORDS])
        if source in documents:
            item = documents[source]
            citation = {"kind": "document", "title": item["title"], "document_id": int(item["document_id"]),
                        "chunk_id": item["chunk_id"], "text": item["text"]}
        elif source in tools:
            citation = {"kind": "tool", "title": tools[source]["title"], "text": tools[source]["text"]}
        elif source in allowed:
            page = pages.get(source, {})
            citation = {"kind": "web", "title": allowed[source].get("title") or source, "url": source,
                        "text": page.get("text") or ""}
        else:
            # A source the answer never had (an invented URL or id) is shown, but never linked.
            citation = {"kind": "unknown", "title": "Unknown source", "text": ""}
        text = citation.pop("text")
        citation.update(n=number, quote=quote,
                        verified=len(quote) >= 8 and _normalized(quote) in _normalized(text))
        citations.append(citation)
    return body, sorted(citations, key=lambda item: item["n"])


def with_footnotes(body: str, citations: list[dict]) -> str:
    """Plain-text rendering for clients without the chat UI (e.g. MCP apps)."""
    if not citations:
        return body
    lines = []
    for citation in citations:
        where = citation.get("url") or citation["title"]
        status = "verified" if citation["verified"] else "not verified"
        lines.append(f"[{citation['n']}] {citation['title']} — “{citation['quote']}” ({status}) {where}".rstrip())
    return body + "\n\nSources:\n" + "\n".join(lines)
