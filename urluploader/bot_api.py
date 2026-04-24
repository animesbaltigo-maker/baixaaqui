from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import aiohttp

from .http_client import get_shared_http_session


STANDARD_BOT_API_UPLOAD_LIMIT = 50 * 1024 * 1024
REMOTE_DOCUMENT_EXTENSIONS = {".pdf", ".zip"}
REMOTE_VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm"}
REMOTE_PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


class BotApiError(Exception):
    """Raised when the HTTP Bot API rejects a request."""


class BotApiClient:
    def __init__(self, token: str, base_url: str, request_timeout: int) -> None:
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.request_timeout = request_timeout

    @property
    def is_local(self) -> bool:
        return "api.telegram.org" not in self.base_url.lower()

    def supports_local_size(self, path: Path) -> bool:
        return self.is_local or path.stat().st_size <= STANDARD_BOT_API_UPLOAD_LIMIT

    def can_try_remote_url(self, url: str, mode: str) -> bool:
        suffix = Path(urlparse(url).path).suffix.lower()
        if mode == "video":
            return suffix in REMOTE_VIDEO_EXTENSIONS
        if mode == "photo":
            return suffix in REMOTE_PHOTO_EXTENSIONS
        return suffix in REMOTE_DOCUMENT_EXTENSIONS

    async def send_remote_url(
        self,
        chat_id: int,
        url: str,
        *,
        caption: str | None,
        mode: str,
    ) -> dict[str, Any]:
        method, field_name = self._method_for_mode(mode)
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "caption": caption or "",
            "parse_mode": "HTML",
        }
        if method == "sendVideo":
            payload["supports_streaming"] = True
        payload[field_name] = url
        return await self._post_json(method, payload)

    async def send_local_file(
        self,
        chat_id: int,
        path: Path,
        *,
        filename: str,
        caption: str | None,
        mode: str,
        thumbnail: Path | None,
    ) -> dict[str, Any]:
        method, field_name = self._method_for_mode(mode)
        data = aiohttp.FormData()
        data.add_field("chat_id", str(chat_id))
        data.add_field("caption", caption or filename)
        data.add_field("parse_mode", "HTML")

        if method == "sendVideo":
            data.add_field("supports_streaming", "true")

        with ExitStack() as stack:
            if self.is_local and path.is_absolute():
                data.add_field(field_name, path.as_uri())
            else:
                file_handle = stack.enter_context(path.open("rb"))
                data.add_field(
                    field_name,
                    file_handle,
                    filename=filename,
                    content_type="application/octet-stream",
                )

            if thumbnail and thumbnail.exists():
                thumb_handle = stack.enter_context(thumbnail.open("rb"))
                data.add_field(
                    "thumbnail",
                    thumb_handle,
                    filename="thumbnail.jpg",
                    content_type="image/jpeg",
                )

            return await self._post_form(method, data)

    def _method_for_mode(self, mode: str) -> tuple[str, str]:
        if mode == "photo":
            return "sendPhoto", "photo"
        if mode == "video":
            return "sendVideo", "video"
        if mode == "audio":
            return "sendAudio", "audio"
        return "sendDocument", "document"

    async def _post_json(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/bot{self.token}/{method}"
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=self.request_timeout)
        session = await get_shared_http_session()
        async with session.post(url, json=payload, timeout=timeout) as response:
            return await self._read_response(response)

    async def _post_form(self, method: str, data: aiohttp.FormData) -> dict[str, Any]:
        url = f"{self.base_url}/bot{self.token}/{method}"
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=self.request_timeout)
        session = await get_shared_http_session()
        async with session.post(url, data=data, timeout=timeout) as response:
            return await self._read_response(response)

    async def _read_response(self, response: aiohttp.ClientResponse) -> dict[str, Any]:
        try:
            payload = await response.json()
        except Exception as exc:
            text = await response.text()
            raise BotApiError(f"HTTP {response.status}: {text[:300]}") from exc

        if response.status >= 400 or not payload.get("ok"):
            description = payload.get("description") or f"HTTP {response.status}"
            raise BotApiError(str(description))
        return payload
