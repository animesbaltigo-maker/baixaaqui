from __future__ import annotations

import asyncio
import logging
import re
import shutil
from pathlib import Path
from urllib.parse import urlparse

import aiohttp

from .http_client import get_shared_http_session
from .models import DownloadResult, RemoteFileInfo
from .names import choose_filename, unique_path
from .progress import ProgressCallback, human_size
from .security import validate_public_url


logger = logging.getLogger(__name__)
FALLBACK_CHUNK_SIZE = 8 * 1024 * 1024


class DownloadError(Exception):
    """Raised when a remote file cannot be downloaded."""


class FileTooLargeError(DownloadError):
    """Raised when a remote file is bigger than the configured limit."""


class RemoteDownloader:
    def __init__(
        self,
        max_file_size: int,
        request_timeout: int,
        *,
        allow_private_downloads: bool = False,
        aria2_connections: int = 8,
        aria2_split: int = 8,
        aria2_min_split_size: str = "1M",
    ) -> None:
        self.max_file_size = max_file_size
        self.request_timeout = request_timeout
        self.allow_private_downloads = allow_private_downloads
        self.aria2_connections = max(1, aria2_connections)
        self.aria2_split = max(1, aria2_split)
        self.aria2_min_split_size = aria2_min_split_size
        self.aria2c = shutil.which("aria2c")

    async def inspect(self, url: str, preferred_filename: str | None = None) -> RemoteFileInfo:
        validate_public_url(url, allow_private=self.allow_private_downloads)
        timeout = aiohttp.ClientTimeout(total=30, sock_connect=15, sock_read=15)
        session = await get_shared_http_session()
        try:
            response = await session.head(url, allow_redirects=True, headers=_headers(), timeout=timeout)
            async with response:
                if response.status < 400 and response.headers:
                    return self._info_from_response(url, response, preferred_filename)
        except aiohttp.ClientError:
            pass

        range_headers = {**_headers(), "Range": "bytes=0-0"}
        try:
            async with session.get(url, allow_redirects=True, headers=range_headers, timeout=timeout) as response:
                if response.status >= 400:
                    raise DownloadError(f"HTTP {response.status} ao acessar o link.")
                return self._info_from_response(url, response, preferred_filename)
        except aiohttp.ClientError as exc:
            raise DownloadError(f"Falha de rede: {exc}") from exc

    def _info_from_response(
        self,
        original_url: str,
        response: aiohttp.ClientResponse,
        preferred_filename: str | None,
    ) -> RemoteFileInfo:
        size = response.content_length
        content_range = response.headers.get("Content-Range", "")
        if content_range and "/" in content_range:
            total_raw = content_range.rsplit("/", 1)[-1]
            if total_raw.isdigit():
                size = int(total_raw)

        filename = choose_filename(str(response.url or original_url), response.headers, preferred_filename)
        return RemoteFileInfo(
            url=str(response.url or original_url),
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
        validate_public_url(url, allow_private=self.allow_private_downloads)
        if self.aria2c and urlparse(url).scheme in {"http", "https"}:
            try:
                info = await self.inspect(url, preferred_filename)
                return await self._download_with_aria2(info, target_dir, progress)
            except (DownloadError, FileTooLargeError):
                raise
            except Exception as exc:
                logger.warning("aria2c_download_fallback url=%s reason=%s", url, exc)

        timeout = aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=self.request_timeout)
        session = await get_shared_http_session()
        try:
            async with session.get(url, allow_redirects=True, headers=_headers(), timeout=timeout) as response:
                if response.status >= 400:
                    raise DownloadError(f"HTTP {response.status} ao acessar o link.")

                total = _declared_size_from_response(response)
                if total and total > self.max_file_size:
                    raise FileTooLargeError(
                        "Arquivo muito grande: "
                        f"{human_size(total)}. Limite: {human_size(self.max_file_size)}."
                    )

                filename = choose_filename(str(response.url), response.headers, preferred_filename)
                target_path = unique_path(target_dir, filename)
                partial_path = target_path.with_name(f"{target_path.name}.part")
                current = 0

                try:
                    with partial_path.open("wb") as file:
                        async for chunk in response.content.iter_chunked(FALLBACK_CHUNK_SIZE):
                            if not chunk:
                                continue
                            current += len(chunk)
                            if current > self.max_file_size:
                                raise FileTooLargeError(
                                    "Arquivo passou do limite durante o download: "
                                    f"{human_size(self.max_file_size)}."
                                )
                            file.write(chunk)
                            await progress(current, total)
                except asyncio.CancelledError:
                    partial_path.unlink(missing_ok=True)
                    raise
                except Exception:
                    partial_path.unlink(missing_ok=True)
                    raise

                partial_path.replace(target_path)
                await progress(current, total)
                return DownloadResult(
                    path=target_path,
                    filename=filename,
                    size=current,
                    mime_type=response.headers.get("Content-Type"),
                )
        except aiohttp.ClientError as exc:
            raise DownloadError(f"Falha de rede: {exc}") from exc

    async def _download_with_aria2(
        self,
        info: RemoteFileInfo,
        target_dir: Path,
        progress: ProgressCallback,
    ) -> DownloadResult:
        if not self.aria2c:
            raise DownloadError("aria2c nao esta disponivel.")
        if info.size and info.size > self.max_file_size:
            raise FileTooLargeError(
                "Arquivo muito grande: "
                f"{human_size(info.size)}. Limite: {human_size(self.max_file_size)}."
            )

        filename = info.filename
        target_path = unique_path(target_dir, filename)
        partial_path = target_path.with_name(f"{target_path.name}.part")
        cmd = [
            self.aria2c,
            "--allow-overwrite=true",
            "--auto-file-renaming=false",
            "--continue=true",
            "--file-allocation=none",
            "--summary-interval=1",
            "--console-log-level=error",
            "--show-console-readout=true",
            f"--max-connection-per-server={self.aria2_connections}",
            f"--split={self.aria2_split}",
            f"--min-split-size={self.aria2_min_split_size}",
            "--max-tries=3",
            "--retry-wait=3",
            "--user-agent=Mozilla/5.0 URLUploadBot/2.0",
            "--dir",
            str(partial_path.parent),
            "--out",
            partial_path.name,
            info.url,
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        current = 0
        total = info.size
        try:
            assert process.stdout is not None
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                current, total = _parse_aria2_progress(line.decode("utf-8", errors="replace"), current, total)
                if current:
                    await progress(current, total)
            return_code = await process.wait()
        except asyncio.CancelledError:
            process.kill()
            await process.wait()
            partial_path.unlink(missing_ok=True)
            raise

        if return_code != 0 or not partial_path.exists():
            partial_path.unlink(missing_ok=True)
            raise DownloadError("O aria2c nao conseguiu concluir o download.")

        size = partial_path.stat().st_size
        if size > self.max_file_size:
            partial_path.unlink(missing_ok=True)
            raise FileTooLargeError(
                "Arquivo muito grande: "
                f"{human_size(size)}. Limite: {human_size(self.max_file_size)}."
            )
        partial_path.replace(target_path)
        await progress(size, total or size)
        return DownloadResult(path=target_path, filename=target_path.name, size=size, mime_type=info.mime_type)


def _headers() -> dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0 URLUploadBot/2.0",
        "Accept": "*/*",
        "Connection": "keep-alive",
    }


def _parse_aria2_progress(line: str, current: int, total: int | None) -> tuple[int, int | None]:
    match = re.search(
        r"(?P<current>[0-9.]+\s*[KMGT]?i?B)/(?P<total>[0-9.]+\s*[KMGT]?i?B)\((?P<pct>\d+)%\)",
        line,
        re.IGNORECASE,
    )
    if not match:
        return current, total
    parsed_current = _size_to_bytes(match.group("current")) or current
    parsed_total = _size_to_bytes(match.group("total")) or total
    return parsed_current, parsed_total


def _declared_size_from_response(response: aiohttp.ClientResponse) -> int | None:
    size = response.content_length
    if size:
        return size
    content_range = response.headers.get("Content-Range", "")
    if content_range and "/" in content_range:
        total_raw = content_range.rsplit("/", 1)[-1]
        if total_raw.isdigit():
            return int(total_raw)
    for header in ("X-Content-Length", "X-Original-Content-Length"):
        raw = response.headers.get(header)
        if raw and raw.isdigit():
            return int(raw)
    return None


def _size_to_bytes(value: str) -> int | None:
    cleaned = value.replace(" ", "")
    match = re.fullmatch(r"(?P<num>\d+(?:\.\d+)?)(?P<unit>[KMGT]?i?B)", cleaned, re.IGNORECASE)
    if not match:
        return None
    number = float(match.group("num"))
    unit = match.group("unit").upper()
    factors = {
        "B": 1,
        "KIB": 1024,
        "MIB": 1024**2,
        "GIB": 1024**3,
        "TIB": 1024**4,
        "KB": 1000,
        "MB": 1000**2,
        "GB": 1000**3,
        "TB": 1000**4,
    }
    factor = factors.get(unit)
    if not factor:
        return None
    return int(number * factor)
