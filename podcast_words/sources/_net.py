"""Outbound-request safety helpers (SSRF mitigation).

Audio enclosure URLs come from podcast feeds, which are only as trustworthy as
the feed itself. Before downloading we enforce that the URL is http(s) and that
its host does not resolve to a private, loopback, link-local, or otherwise
reserved address — blocking attempts to pivot at internal services or cloud
metadata endpoints (e.g. 169.254.169.254).
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

_ALLOWED_SCHEMES = {"http", "https"}


class UnsafeURLError(ValueError):
    """Raised when an outbound URL is disallowed by the SSRF guard."""


def _addresses_for(host: str) -> list[ipaddress._BaseAddress]:
    infos = socket.getaddrinfo(host, None)
    addrs: list[ipaddress._BaseAddress] = []
    for info in infos:
        sockaddr = info[4]
        addrs.append(ipaddress.ip_address(sockaddr[0]))
    return addrs


def assert_safe_url(url: str) -> None:
    """Raise UnsafeURLError if `url` is not a public http(s) resource."""
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise UnsafeURLError(
            f"Refusing non-http(s) URL scheme '{parsed.scheme}://'."
        )
    host = parsed.hostname
    if not host:
        raise UnsafeURLError("URL has no host.")

    try:
        addresses = _addresses_for(host)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"Could not resolve host '{host}'.") from exc

    for addr in addresses:
        if (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_reserved
            or addr.is_multicast
            or addr.is_unspecified
        ):
            raise UnsafeURLError(
                f"Host '{host}' resolves to a non-public address ({addr}); "
                "blocked to prevent SSRF."
            )
