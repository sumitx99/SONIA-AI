"""Optional browser snapshots for pages that need JavaScript or visual review."""

import json
import logging
import os
import re
import time
from urllib.parse import urlsplit

import requests

from app.services.source_reader import PageText, public_addresses

logger = logging.getLogger(__name__)
CRAWL_WAIT_SECONDS = 35
CRAWL_POLL_INTERVAL = 2


def _read_json(response):
    response.raise_for_status()
    raw = bytearray()
    for chunk in response.iter_content(65536):
        raw.extend(chunk)
        if len(raw) > 3_000_000:
            raise ValueError("Browser response exceeded its size limit")
    return json.loads(raw)


def _page_text(html):
    parser = PageText(include_head=False)
    parser.feed(html if isinstance(html, str) else "")
    return " ".join(" ".join(parser.parts).split())[:6000]


def _crawl_page(endpoint, headers, payload):
    url = payload["url"]
    with requests.post(endpoint, headers=headers, json={
        **payload, "limit": 1, "depth": 0, "source": "links", "render": True,
        "formats": ["html"], "crawlPurposes": ["ai-input"],
    }, timeout=(3, 8), allow_redirects=False, stream=True) as response:
        started = _read_json(response)
    job_id = started.get("result")
    if not started.get("success") or not isinstance(job_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", job_id):
        raise ValueError("Cloudflare did not return a crawl job ID")

    job_url = f"{endpoint}/{job_id}"
    deadline = time.monotonic() + CRAWL_WAIT_SECONDS
    terminal = False
    logger.info("Polling Cloudflare single-page crawl")
    try:
        while (remaining := deadline - time.monotonic()) > 0:
            try:
                with requests.get(job_url, headers=headers, params={"limit": 1},
                                  timeout=min(5, remaining), allow_redirects=False, stream=True) as response:
                    state = _read_json(response)
            except requests.Timeout:
                state = None
            if state is not None:
                job = state.get("result")
                if not state.get("success") or not isinstance(job, dict):
                    raise ValueError("Cloudflare did not return crawl status")
                status = job.get("status")
                if status == "completed":
                    terminal = True
                    for record in job.get("records") or []:
                        meta = record.get("metadata") or {}
                        final = urlsplit(meta.get("url") or record.get("url") or "")
                        target = urlsplit(url)
                        if (record.get("url") == url and record.get("status") == "completed"
                                and record.get("outcome", "success") == "success"
                                and meta.get("status", 200) == 200 and final.scheme == "https"
                                and final.netloc == target.netloc):
                            return _page_text(record.get("html"))
                    logger.warning("Cloudflare crawl completed without readable content for the requested page")
                    return ""
                if status in {"errored", "cancelled_by_user", "cancelled_due_to_limits", "cancelled_due_to_timeout"}:
                    terminal = True
                    logger.warning("Cloudflare crawl ended with status %s", status)
                    return ""
                if status not in {"queued", "running"}:
                    raise ValueError("Cloudflare returned an unknown crawl status")
            time.sleep(max(0, min(CRAWL_POLL_INTERVAL, deadline - time.monotonic())))
        logger.warning("Cloudflare crawl exceeded the polling deadline")
        return ""
    finally:
        if not terminal:
            try:
                with requests.delete(job_url, headers=headers, timeout=(2, 3),
                                     allow_redirects=False, stream=True) as response:
                    response.raise_for_status()
            except requests.RequestException:
                logger.warning("Cloudflare crawl could not be cancelled")


def render_page(url: str, *, screenshot: bool) -> tuple[str, str | None]:
    account = os.getenv("CLOUDFLARE_BROWSER_ACCOUNT_ID", "").strip()
    token = os.getenv("CLOUDFLARE_BROWSER_API_TOKEN", "").strip()
    if not re.fullmatch(r"[a-fA-F0-9]{32}", account) or not token:
        return "", None

    target = urlsplit(url)
    if (target.scheme != "https" or not target.hostname or target.port not in (None, 443)
            or target.username or target.password or target.query):
        return "", None
    public_addresses(target.hostname)
    host = re.escape(target.hostname.encode("idna").decode("ascii"))
    payload = {
        "url": url,
        "allowRequestPattern": [rf"^https://{host}(?::443)?/"],
        "gotoOptions": {"waitUntil": "networkidle2", "timeout": 8000},
    }
    action = "snapshot" if screenshot else "content"
    if screenshot:
        payload.update({
            "formats": ["content", "screenshot"],
            "actionTimeout": 4000,
            "viewport": {"width": 1280, "height": 800},
            "screenshotOptions": {"type": "jpeg", "quality": 70},
        })
    base = f"https://api.cloudflare.com/client/v4/accounts/{account}/browser-run"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        with requests.post(f"{base}/{action}", params={"cacheTTL": 0}, json=payload,
                           headers=headers, timeout=(3, 15), allow_redirects=False, stream=True) as response:
            data = _read_json(response)
    except requests.ReadTimeout:
        logger.info("Cloudflare direct render timed out; starting a crawl")
        crawl_payload = {key: payload[key] for key in ("url", "allowRequestPattern", "gotoOptions")}
        return _crawl_page(f"{base}/crawl", headers, crawl_payload), None
    meta = data.get("meta") or {}
    # Cloudflare may omit finalUrl when no redirect is reported.
    final = urlsplit(meta.get("finalUrl") or url)
    if (not data.get("success") or meta.get("status", 200) != 200
            or final.scheme != "https" or final.hostname != target.hostname):
        logger.warning("Cloudflare browser %s returned no usable page", action)
        return "", None
    result = data.get("result")
    if screenshot:
        if not isinstance(result, dict):
            return "", None
        html, image = result.get("content"), result.get("screenshot")
    else:
        html, image = result, None
    text = _page_text(html)
    if not isinstance(image, str) or not image.startswith("/9j/") or len(image) > 800_000:
        image = None
    return text, image
