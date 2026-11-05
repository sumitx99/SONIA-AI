"""Optional browser snapshots for pages that need JavaScript or visual review."""

import json
import os
import re
from urllib.parse import urlsplit

import requests

from app.services.source_reader import PageText, public_addresses


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
        "formats": ["content", "screenshot"] if screenshot else ["content"],
        "gotoOptions": {"waitUntil": "networkidle2", "timeout": 8000},
        "actionTimeout": 4000,
        "viewport": {"width": 1280, "height": 800},
        "screenshotOptions": {"type": "jpeg", "quality": 70},
    }
    endpoint = f"https://api.cloudflare.com/client/v4/accounts/{account}/browser-rendering/snapshot"
    with requests.post(endpoint, params={"cacheTTL": 0}, json=payload,
                       headers={"Authorization": f"Bearer {token}"},
                       timeout=(3, 15), allow_redirects=False, stream=True) as response:
        response.raise_for_status()
        raw = bytearray()
        for chunk in response.iter_content(65536):
            raw.extend(chunk)
            if len(raw) > 3_000_000:
                raise ValueError("Browser snapshot exceeded its size limit")
    snapshot = json.loads(raw)
    meta = snapshot.get("meta") or {}
    final = urlsplit(meta.get("finalUrl") or "")
    if (not snapshot.get("success") or meta.get("status") != 200
            or final.scheme != "https" or final.hostname != target.hostname):
        return "", None
    result = snapshot.get("result") or {}
    parser = PageText(include_head=False)
    parser.feed(result.get("content") or "")
    text = " ".join(" ".join(parser.parts).split())[:6000]
    image = result.get("screenshot")
    if not screenshot or not isinstance(image, str) or not image.startswith("/9j/") or len(image) > 800_000:
        image = None
    return text, image
