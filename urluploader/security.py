from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

import aiohttp

from .errors import UnsupportedUrlError


BLOCKED_HOSTS = {"localhost", "localhost.localdomain"}


def validate_public_url(url: str, *, allow_private: bool = False) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise UnsupportedUrlError("Esse link usa um esquema nao suportado.")
    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        raise UnsupportedUrlError("Esse link nao tem um host valido.")
    if allow_private:
        return
    if hostname in BLOCKED_HOSTS or hostname.endswith(".local"):
        raise UnsupportedUrlError("Links locais ou internos nao sao permitidos.")
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        return
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
        raise UnsupportedUrlError("Links para IPs internos nao sao permitidos.")


def is_public_http_url(url: str) -> bool:
    try:
        validate_public_url(url, allow_private=False)
        return True
    except UnsupportedUrlError:
        return False


async def check_public_url_head(url: str, timeout_seconds: int = 10) -> tuple[bool, str]:
    timeout = aiohttp.ClientTimeout(total=timeout_seconds, sock_connect=timeout_seconds / 2, sock_read=timeout_seconds / 2)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.head(url, allow_redirects=True) as response:
                if response.status < 400:
                    return True, f"HTTP {response.status}"
            async with session.get(url, allow_redirects=True, headers={"Range": "bytes=0-0"}) as response:
                return response.status < 400, f"HTTP {response.status}"
    except Exception as exc:
        return False, str(exc)
