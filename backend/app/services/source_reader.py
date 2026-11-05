"""Read public source pages for citation verification, with pinned public DNS addresses."""
import ipaddress
import os
import socket
from html.parser import HTMLParser
from urllib.parse import urlsplit, urljoin

import urllib3


# Sites such as Wikimedia refuse automated requests whose User-Agent gives no way to contact the
# operator, especially from cloud servers. Name the app and its public address.
USER_AGENT = f"Sonia/1.0 (+{os.getenv('FRONTEND_PUBLIC_URL', 'https://sonia-ai-murp.vercel.app').strip()})"


class PageText(HTMLParser):
    def __init__(self, *, include_head=True):
        super().__init__()
        self.hidden_tags = {"script", "style", "noscript", "svg"}
        if not include_head:
            self.hidden_tags.update({"head", "title"})
        self.hidden = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in self.hidden_tags:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in self.hidden_tags:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden and data.strip():
            self.parts.append(data.strip())


def public_addresses(host):
    addresses = list(dict.fromkeys(item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)))
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise ValueError("Only public source pages may be read")
    return addresses


def read_public_resource(url, max_bytes=1_000_000, allowed_types=("text/html", "text/plain", "application/json")):
    """No cookies/auth, no private addresses/ports, bounded bytes and redirects.

    Connect directly to the validated IP with the original TLS hostname, avoiding
    a second DNS lookup (DNS rebinding). Redirect destinations are validated again.
    """
    for _ in range(4):
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Invalid public source URL")
        if parsed.port not in {None, 80 if parsed.scheme == "http" else 443}:
            raise ValueError("Nonstandard source port")
        ip = public_addresses(parsed.hostname)[0]
        pool_type = urllib3.HTTPSConnectionPool if parsed.scheme == "https" else urllib3.HTTPConnectionPool
        options = {"assert_hostname": parsed.hostname, "server_hostname": parsed.hostname} if parsed.scheme == "https" else {}
        with pool_type(ip, port=parsed.port or (443 if parsed.scheme == "https" else 80),
                       timeout=urllib3.Timeout(connect=3, read=5), retries=False, **options) as pool:
            path = (parsed.path or "/") + ("?" + parsed.query if parsed.query else "")
            response = pool.urlopen("GET", path, headers={"Host": parsed.hostname, "User-Agent": USER_AGENT,
                                                        "Accept-Encoding": "identity"},
                                    redirect=False, preload_content=False)
            try:
                if response.status in {301, 302, 303, 307, 308}:
                    url = urljoin(url, response.headers.get("Location", ""))
                    continue
                if response.status != 200:
                    raise ValueError(f"Source could not be downloaded (HTTP {response.status})")
                content_type = response.headers.get("Content-Type", "").lower()
                if not any(kind in content_type for kind in allowed_types):
                    raise ValueError(f"Unsupported source content type ({content_type or 'none'})")
                data = response.read(max_bytes + 1, decode_content=False)
                if len(data) > max_bytes:
                    raise ValueError("Source exceeds download limit")
                return data, content_type
            finally:
                response.close()
    raise ValueError("Too many source redirects")


def read_source(url, *, include_head=True):
    data, content_type = read_public_resource(url)
    text = data.decode("utf-8", errors="replace")
    if "text/html" in content_type:
        parser = PageText(include_head=include_head)
        parser.feed(text)
        text = " ".join(parser.parts)
    return " ".join(text.split())[:30_000]
