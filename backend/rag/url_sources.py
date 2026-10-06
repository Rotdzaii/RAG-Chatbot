"""Fetch public VLU pages without redirects, proxy use or DNS rebinding."""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import time
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit


ALLOWED_HOSTS = frozenset({"www.vlu.edu.vn", "vlu.edu.vn"})
BLOCKED_IPV4_ADDRESSES = frozenset({ipaddress.IPv4Address("168.63.129.16")})
ALLOWED_CONTENT_TYPES = frozenset(
    {"text/html", "text/plain", "application/pdf"}
)
MAX_URL_BYTES = 10 * 1024 * 1024
CONNECT_TIMEOUT_SECONDS = 8
TOTAL_TIMEOUT_SECONDS = 20


class SourceURLValidationError(ValueError):
    pass


class SourceFetchError(Exception):
    pass


class UnsupportedSourceType(SourceFetchError):
    pass


class SourceTooLarge(SourceFetchError):
    pass


@dataclass(frozen=True, slots=True)
class FetchedSource:
    url: str
    filename: str
    mime_type: str
    content: bytes


def normalize_source_url(value: str) -> str:
    if not value or len(value) > 2048 or value != value.strip():
        raise SourceURLValidationError("Invalid source URL")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise SourceURLValidationError("Invalid source URL")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise SourceURLValidationError("Invalid source URL") from error
    if (
        parsed.scheme != "https"
        or parsed.hostname not in ALLOWED_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.fragment
    ):
        raise SourceURLValidationError("Only HTTPS URLs on VLU hosts are allowed")
    return urlunsplit(("https", parsed.hostname, parsed.path or "/", parsed.query, ""))


def _public_addresses(host: str) -> list[str]:
    try:
        addresses = socket.getaddrinfo(
            host, 443, family=socket.AF_INET, type=socket.SOCK_STREAM
        )
    except OSError as error:
        raise SourceFetchError("Source is unavailable") from error
    ips = list(dict.fromkeys(item[4][0] for item in addresses))
    if not ips:
        raise SourceFetchError("Source is unavailable")
    try:
        for ip in ips:
            address = ipaddress.ip_address(ip)
            if (
                not isinstance(address, ipaddress.IPv4Address)
                or not address.is_global
                or address in BLOCKED_IPV4_ADDRESSES
            ):
                raise SourceFetchError("Source address is not public")
    except ValueError as error:
        raise SourceFetchError("Source address is not public") from error
    return ips


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, ip: str) -> None:
        super().__init__(
            host,
            timeout=CONNECT_TIMEOUT_SECONDS,
            context=ssl.create_default_context(),
        )
        self._ip = ip

    def connect(self) -> None:
        # Connect to the checked IP, but validate the certificate for the VLU
        # hostname (SNI and Host header use self.host). No proxy is involved.
        raw = socket.create_connection((self._ip, 443), timeout=self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise


def _filename(path: str, mime_type: str) -> str:
    segment = path.rsplit("/", 1)[-1] or "index"
    if not segment.isascii() or not all(
        char.isalnum() or char in "-_." for char in segment
    ):
        segment = "page"
    suffix = {"text/html": ".html", "text/plain": ".txt", "application/pdf": ".pdf"}[
        mime_type
    ]
    if not segment.lower().endswith(suffix):
        segment += suffix
    return segment[: 255 - len(suffix)] + suffix if len(segment) > 255 else segment


def fetch_source(url: str) -> FetchedSource:
    normalized = normalize_source_url(url)
    parsed = urlsplit(normalized)
    host = parsed.hostname
    assert host is not None  # normalize_source_url already checked it.
    ip = _public_addresses(host)[0]
    connection = _PinnedHTTPSConnection(host, ip)
    target = parsed.path + (f"?{parsed.query}" if parsed.query else "")
    try:
        connection.request(
            "GET",
            target,
            headers={
                "Accept": "text/html, text/plain, application/pdf",
                "Accept-Encoding": "identity",
                "User-Agent": "VLU-RAG-Chatbot/1.0",
            },
        )
        response = connection.getresponse()
        if response.status != 200:
            # Never follow redirects, even to another URL on the same host.
            raise SourceFetchError("Source returned an unsuccessful status")
        mime_type = response.getheader("Content-Type", "").split(";", 1)[0].strip().lower()
        if mime_type not in ALLOWED_CONTENT_TYPES:
            raise UnsupportedSourceType("Unsupported source MIME type")
        if response.getheader("Content-Encoding", "identity").lower() != "identity":
            raise UnsupportedSourceType("Compressed sources are not supported")
        length = response.getheader("Content-Length")
        if length is not None:
            try:
                if int(length) > MAX_URL_BYTES:
                    raise SourceTooLarge("Source exceeds 10 MiB")
            except ValueError as error:
                raise SourceFetchError("Invalid source response") from error

        deadline = time.monotonic() + TOTAL_TIMEOUT_SECONDS
        content = bytearray()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SourceFetchError("Source is unavailable")
            assert connection.sock is not None
            connection.sock.settimeout(min(CONNECT_TIMEOUT_SECONDS, remaining))
            block = response.read(min(65536, MAX_URL_BYTES + 1 - len(content)))
            if not block:
                break
            content.extend(block)
            if len(content) > MAX_URL_BYTES:
                raise SourceTooLarge("Source exceeds 10 MiB")
        if not content:
            raise SourceFetchError("Source has no content")
        return FetchedSource(
            url=normalized,
            filename=_filename(parsed.path, mime_type),
            mime_type=mime_type,
            content=bytes(content),
        )
    except (OSError, TimeoutError, http.client.HTTPException) as error:
        raise SourceFetchError("Source is unavailable") from error
    finally:
        connection.close()
