from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import TypedDict
from urllib.parse import urljoin

from aiohttp import (
    ClientError,
    ClientSession,
    ClientTimeout,
    DummyCookieJar,
    TCPConnector,
)
from aiohttp.abc import AbstractResolver
from aiohttp.resolver import DefaultResolver
from yarl import URL


MAX_BODY_BYTES = 128 * 1024
MAX_REDIRECTS = 5
FETCH_TIMEOUT = 5
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})

_REQUEST_HEADERS = {
    "User-Agent": "AstrBot-QZone-Link-Preview/1.0",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Encoding": "identity",
}
_HTML_CONTENT_TYPES = {"text/html", "application/xhtml+xml"}

_IPV4_DENY_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.0.0.0/24",
        "192.0.2.0/24",
        "192.31.196.0/24",
        "192.52.193.0/24",
        "192.88.99.0/24",
        "192.168.0.0/16",
        "192.175.48.0/24",
        "198.18.0.0/15",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "224.0.0.0/4",
        "240.0.0.0/4",
    )
)
_IPV6_GLOBAL_UNICAST = ipaddress.ip_network("2000::/3")
_IPV6_DENY_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in (
        "::/128",
        "::1/128",
        "64:ff9b::/96",
        "64:ff9b:1::/48",
        "100::/64",
        "2001::/23",
        "2001:db8::/32",
        "2002::/16",
        "3fff::/20",
        "fc00::/7",
        "fe80::/10",
        "ff00::/8",
    )
)


class _ResolveRecord(TypedDict):
    hostname: str
    host: str
    port: int
    family: int
    proto: int
    flags: int


@dataclass(frozen=True, slots=True)
class LinkPreview:
    title: str
    url: str


class _TitleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_title = False
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._parts.append(data)

    @property
    def title(self) -> str:
        return " ".join("".join(self._parts).split())


def _is_public_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(address, ipaddress.IPv4Address):
        return not any(address in network for network in _IPV4_DENY_NETWORKS)

    mapped_address = getattr(address, "ipv4_mapped", None)
    if mapped_address is not None:
        return _is_public_address(mapped_address)
    return address in _IPV6_GLOBAL_UNICAST and not any(
        address in network for network in _IPV6_DENY_NETWORKS
    )


class _SafeResolver(AbstractResolver):
    def __init__(self, resolver: AbstractResolver | None = None) -> None:
        self._resolver = resolver if resolver is not None else DefaultResolver()
        self._closed = False

    async def resolve(
        self,
        host: str,
        port: int = 0,
        family: int = socket.AF_INET,
    ) -> list[_ResolveRecord]:
        records = await self._resolver.resolve(host, port, family)
        try:
            if not records or not all(
                _is_public_address(ipaddress.ip_address(record["host"]))
                for record in records
            ):
                raise OSError("DNS did not resolve exclusively to public addresses")
        except (KeyError, TypeError, ValueError, IndexError) as error:
            raise OSError(
                "DNS did not resolve exclusively to public addresses"
            ) from error
        return records

    async def close(self) -> None:
        if not self._closed:
            await self._resolver.close()
            self._closed = True


def _is_safe_url(url: str) -> bool:
    try:
        parsed = URL(url)
        if parsed.scheme.lower() not in {"http", "https"}:
            return False
        hostname = parsed.raw_host
        if not hostname or parsed.user is not None or parsed.password is not None:
            return False

        parsed.port

        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            try:
                socket.inet_aton(hostname)
            except (OSError, UnicodeError):
                return True
            return False
        return _is_public_address(address)
    except (UnicodeError, ValueError, TypeError):
        return False


def _hostname(url: str) -> str:
    return URL(url).host or url


def _html_title(body: bytes, charset: str | None) -> str:
    try:
        text = body[:MAX_BODY_BYTES].decode(charset or "utf-8", errors="replace")
    except LookupError:
        text = body[:MAX_BODY_BYTES].decode("utf-8", errors="replace")
    parser = _TitleParser()
    parser.feed(text)
    return parser.title


async def _read_bounded(content) -> bytes:
    body = bytearray()
    while len(body) < MAX_BODY_BYTES:
        remaining = MAX_BODY_BYTES - len(body)
        chunk = await content.read(remaining)
        if not chunk:
            break
        body.extend(chunk[:remaining])
    return bytes(body)


async def _inspect_link(session, original_url: str) -> LinkPreview:
    current_url = original_url
    redirects_followed = 0

    while True:
        if not _is_safe_url(current_url):
            return LinkPreview("访问失败", original_url)

        async with session.get(
            current_url,
            allow_redirects=False,
        ) as response:
            if response.status in REDIRECT_STATUSES:
                location = response.headers.get("Location")
                if location is None or redirects_followed >= MAX_REDIRECTS:
                    return LinkPreview(f"HTTP {response.status}", original_url)
                current_url = urljoin(current_url, location)
                redirects_followed += 1
                continue

            if not 200 <= response.status < 300:
                return LinkPreview(f"HTTP {response.status}", original_url)

            hostname = _hostname(current_url)
            content_encoding = response.headers.get("Content-Encoding", "").strip()
            if content_encoding and content_encoding.lower() != "identity":
                return LinkPreview(hostname, original_url)
            if response.content_type.lower() not in _HTML_CONTENT_TYPES:
                return LinkPreview(hostname, original_url)

            body = await _read_bounded(response.content)
            return LinkPreview(
                _html_title(body, response.charset) or hostname,
                original_url,
            )


async def inspect_link(url: str) -> LinkPreview:
    async def inspect_with_dedicated_session() -> LinkPreview:
        resolver = _SafeResolver()
        connector = None
        try:
            connector = TCPConnector(resolver=resolver)
            async with ClientSession(
                connector=connector,
                headers=_REQUEST_HEADERS,
                cookie_jar=DummyCookieJar(),
                auto_decompress=False,
                trust_env=False,
                timeout=ClientTimeout(total=FETCH_TIMEOUT),
            ) as session:
                return await _inspect_link(session, url)
        finally:
            if connector is not None and not connector.closed:
                await connector.close()
            await resolver.close()

    try:
        return await asyncio.wait_for(
            inspect_with_dedicated_session(),
            timeout=FETCH_TIMEOUT,
        )
    except asyncio.TimeoutError:
        return LinkPreview("请求超时", url)
    except (ClientError, LookupError, OSError, UnicodeError, ValueError):
        return LinkPreview("访问失败", url)
