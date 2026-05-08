from __future__ import annotations

import asyncio
import re
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

import aiohttp

from .http_client import get_shared_http_session
from .models import DownloadResult, RemoteFileInfo
from .names import choose_filename, sanitize_filename, unique_path
from .progress import ProgressCallback, human_size
from .security import validate_public_url


DRIVE_HOSTS = {"drive.google.com", "docs.google.com", "drive.usercontent.google.com"}
DOWNLOAD_URL = "https://drive.google.com/uc"


class DriveDownloadError(Exception):
    """Raised when a public Google Drive file cannot be resolved or downloaded."""


def is_drive_url(url: str) -> bool:
    hostname = (urlparse(url).hostname or "").lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    return hostname in DRIVE_HOSTS or hostname.endswith(".googleusercontent.com")


def extract_drive_file_id(url: str) -> str | None:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    if query.get("id"):
        return query["id"][0]
    match = re.search(r"/file/d/([^/]+)", parsed.path)
    if match:
        return match.group(1)
    match = re.search(r"/d/([^/]+)", parsed.path)
    if match:
        return match.group(1)
    return None


class GoogleDriveDownloader:
    def __init__(self, max_file_size: int, request_timeout: int) -> None:
        self.max_file_size = max_file_size
        self.request_timeout = request_timeout

    async def inspect(self, url: str, preferred_filename: str | None = None) -> RemoteFileInfo:
        file_id = extract_drive_file_id(url)
        if not file_id:
            raise DriveDownloadError("Esse link do Google Drive nao contem um arquivo valido.")
        async with await self._open_download(file_id, range_probe=True) as response:
            if response.status >= 400:
                raise DriveDownloadError(f"O Google Drive recusou o link: HTTP {response.status}.")
            size = _size_from_headers(response.headers)
            filename = choose_filename(str(response.url), response.headers, preferred_filename)
            if filename == "download.bin":
                filename = f"google-drive-{file_id}.bin"
            return RemoteFileInfo(
                url=url,
                filename=filename,
                size=size,
                mime_type=response.headers.get("Content-Type"),
            )

    async def download(
        self,
        url: str,
        target_dir: Path,
        preferred_filename: str | None,
        progress: ProgressCallback,
    ) -> DownloadResult:
        file_id = extract_drive_file_id(url)
        if not file_id:
            raise DriveDownloadError("Esse link do Google Drive nao contem um arquivo valido.")

        async with await self._open_download(file_id, range_probe=False) as response:
            if response.status >= 400:
                raise DriveDownloadError(f"O Google Drive recusou o download: HTTP {response.status}.")
            total = _size_from_headers(response.headers)
            if total and total > self.max_file_size:
                raise DriveDownloadError(f"Arquivo muito grande: {human_size(total)}. Limite: {human_size(self.max_file_size)}.")

            filename = choose_filename(str(response.url), response.headers, preferred_filename)
            if filename == "download.bin":
                filename = f"google-drive-{file_id}.bin"
            filename = sanitize_filename(filename) or f"google-drive-{file_id}.bin"
            target_path = unique_path(target_dir, filename)
            current = 0
            try:
                with target_path.open("wb") as file:
                    async for chunk in response.content.iter_chunked(4 * 1024 * 1024):
                        if not chunk:
                            continue
                        current += len(chunk)
                        if current > self.max_file_size:
                            raise DriveDownloadError(f"Arquivo passou do limite: {human_size(self.max_file_size)}.")
                        file.write(chunk)
                        await progress(current, total)
            except asyncio.CancelledError:
                target_path.unlink(missing_ok=True)
                raise
            except Exception:
                target_path.unlink(missing_ok=True)
                raise

            await progress(current, total or current)
            return DownloadResult(target_path, target_path.name, current, response.headers.get("Content-Type"))

    async def _open_download(self, file_id: str, *, range_probe: bool) -> aiohttp.ClientResponse:
        session = await get_shared_http_session()
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=self.request_timeout)
        headers = _headers()
        if range_probe:
            headers["Range"] = "bytes=0-0"
        params = {"export": "download", "id": file_id}
        response = await session.get(DOWNLOAD_URL, params=params, headers=headers, allow_redirects=True, timeout=timeout)
        if _looks_like_file(response):
            return response

        text = await response.text(errors="replace")
        response.release()
        confirm_url = _extract_confirm_url(text, str(response.url))
        if not confirm_url:
            raise DriveDownloadError("Esse arquivo do Google Drive exige login/permissao ou nao esta publico.")
        response = await session.get(confirm_url, headers=headers, allow_redirects=True, timeout=timeout)
        if not _looks_like_file(response):
            response.release()
            raise DriveDownloadError("Nao consegui confirmar o download publico no Google Drive.")
        return response


def _looks_like_file(response: aiohttp.ClientResponse) -> bool:
    content_disposition = response.headers.get("Content-Disposition", "")
    content_type = response.headers.get("Content-Type", "").lower()
    return "attachment" in content_disposition.lower() or not content_type.startswith("text/html")


def _extract_confirm_url(html: str, base_url: str) -> str | None:
    href_patterns = [
        r'href="([^"]*(?:uc|download)[^"]*confirm=[^"]+)"',
        r"href='([^']*(?:uc|download)[^']*confirm=[^']+)'",
    ]
    for pattern in href_patterns:
        match = re.search(pattern, html)
        if match:
            return urljoin(base_url, match.group(1).replace("&amp;", "&"))

    form_match = re.search(r'<form[^>]+action="([^"]+)"[^>]*>(.*?)</form>', html, flags=re.IGNORECASE | re.DOTALL)
    if form_match:
        action = urljoin(base_url, form_match.group(1).replace("&amp;", "&"))
        inputs = dict(re.findall(r'name="([^"]+)"\s+value="([^"]*)"', form_match.group(2)))
        if inputs:
            return f"{action}?{urlencode(inputs)}"
    return None


def _size_from_headers(headers: aiohttp.typedefs.LooseHeaders) -> int | None:
    content_range = str(headers.get("Content-Range") or "")
    if "/" in content_range:
        total = content_range.rsplit("/", 1)[-1]
        if total.isdigit():
            return int(total)
    raw_length = headers.get("Content-Length")
    try:
        return int(str(raw_length)) if raw_length is not None else None
    except ValueError:
        return None


def _headers() -> dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0 BaixaAquiBot/2.0",
        "Accept": "*/*",
        "Connection": "keep-alive",
    }
