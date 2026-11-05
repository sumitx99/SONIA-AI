"""Optional browser snapshots for pages that need JavaScript or visual review."""

import json
import logging
import os
import re
from urllib.parse import urlsplit

import requests

from app.services.source_reader import PageText, public_addresses

logger = logging.getLogger(__name__)


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
    endpoint = f"https://api.cloudflare.com/client/v4/accounts/{account}/browser-run/{action}"
    with requests.post(endpoint, params={"cacheTTL": 0}, json=payload,
                       headers={"Authorization": f"Bearer {token}"},
                       timeout=(3, 15), allow_redirects=False, stream=True) as response:
        response.raise_for_status()
        raw = bytearray()
        for chunk in response.iter_content(65536):
            raw.extend(chunk)
            if len(raw) > 3_000_000:
                raise ValueError("Browser snapshot exceeded its size limit")
    data = json.loads(raw)
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
    parser = PageText(include_head=False)
    parser.feed(html if isinstance(html, str) else "")
    text = " ".join(" ".join(parser.parts).split())[:6000]
    if not isinstance(image, str) or not image.startswith("/9j/") or len(image) > 800_000:
        image = None
    return text, image
