"""Checks on user-supplied MCP server URLs before this server connects to them (SSRF).

Only public https endpoints are allowed: loopback, private, link-local (cloud metadata
such as 169.254.169.254), carrier-grade NAT, multicast and reserved addresses are refused,
after resolving the hostname. MCP_ALLOW_PRIVATE_URLS=true lifts this for local development.
"""

import asyncio
import ipaddress
import os
import socket
from urllib.parse import urlsplit


class UnsafeURLError(ValueError):
    """The URL may not be used as an MCP server."""


def _private_allowed() -> bool:
    return os.getenv("MCP_ALLOW_PRIVATE_URLS", "false").strip().lower() == "true"


def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def normalize_url(url: str) -> str:
    """Validates the URL's form and returns it without surrounding spaces."""
    url = (url or "").strip()
    parts = urlsplit(url)
    allowed_schemes = {"https", "http"} if _private_allowed() else {"https"}
    if parts.scheme not in allowed_schemes:
        raise UnsafeURLError("Use an https:// URL for the MCP server.")
    if not parts.hostname:
        raise UnsafeURLError("The URL has no host name.")
    if parts.username or parts.password:
        raise UnsafeURLError("Put credentials in the connection's header, not in the URL.")
    if len(url) > 2048:
        raise UnsafeURLError("The URL is too long.")
    return url


async def assert_public_url(url: str) -> str:
    """Raises UnsafeURLError unless every address the host resolves to is public."""
    url = normalize_url(url)
    if _private_allowed():
        return url
    parts = urlsplit(url)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(parts.hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise UnsafeURLError(f"{parts.hostname} could not be found.") from None
    addresses = {info[4][0] for info in infos}
    if not addresses or not all(_is_public(address) for address in addresses):
        raise UnsafeURLError("That address points to a private or local network, which isn't allowed.")
    return url
