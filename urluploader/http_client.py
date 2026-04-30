from __future__ import annotations

import asyncio

import aiohttp


_session_lock = asyncio.Lock()
_shared_session: aiohttp.ClientSession | None = None


async def get_shared_http_session() -> aiohttp.ClientSession:
    global _shared_session
    if _shared_session and not _shared_session.closed:
        return _shared_session

    async with _session_lock:
        if _shared_session and not _shared_session.closed:
            return _shared_session
        connector = aiohttp.TCPConnector(
            limit=400,
            limit_per_host=80,
            ttl_dns_cache=300,
            enable_cleanup_closed=True,
        )
        _shared_session = aiohttp.ClientSession(connector=connector)
        return _shared_session


async def close_shared_http_session() -> None:
    global _shared_session
    if _shared_session and not _shared_session.closed:
        await _shared_session.close()
    _shared_session = None
