"""Read public source pages for citation verification, with pinned public DNS addresses."""
import ipaddress
import socket
from html.parser import HTMLParser
from urllib.parse import urlsplit, urljoin

import urllib3


class PageText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hidden = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "svg"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden and data.strip():
            self.parts.append(data.strip())


def public_addresses(host):
    addresses = list(dict.fromkeys(item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)))
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise ValueError("Only public source pages may be read")
    return addresses


def read_source(url):
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
            response = pool.urlopen("GET", path, headers={"Host": parsed.hostname, "User-Agent": "Sonia-SourceVerifier/1.0",
                                                        "Accept-Encoding": "identity"},
                                    redirect=False, preload_content=False)
            try:
                if response.status in {301, 302, 303, 307, 308}:
                    url = urljoin(url, response.headers.get("Location", ""))
                    continue
                if response.status != 200:
                    return ""
                content_type = response.headers.get("Content-Type", "").lower()
                if not any(kind in content_type for kind in ("text/html", "text/plain", "application/json")):
                    return ""
                data = response.read(1_000_001, decode_content=False)
                if len(data) > 1_000_000:
                    return ""
                text = data.decode("utf-8", errors="replace")
                if "text/html" in content_type:
                    parser = PageText()
                    parser.feed(text)
                    text = " ".join(parser.parts)
                return " ".join(text.split())[:30_000]
            finally:
                response.close()
    return ""
