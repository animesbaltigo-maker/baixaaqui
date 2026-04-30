from __future__ import annotations

import json
import mimetypes
from io import BytesIO
from pathlib import Path

import aiohttp

from .http_client import get_shared_http_session


class ImageHostError(Exception):
    """Raised when an image host fails to upload an image."""


class CatboxImageHost:
    def __init__(self, endpoint: str = "https://catbox.moe/user/api.php") -> None:
        self.endpoint = endpoint

    async def upload(self, path: Path) -> str:
        with path.open("rb") as image:
            return await self.upload_bytes(path.name, image, mimetypes.guess_type(path.name)[0] or "application/octet-stream")

    async def upload_bytes(self, filename: str, data_source, content_type: str | None = None) -> str:
        timeout = aiohttp.ClientTimeout(total=45, sock_connect=12, sock_read=30)
        data = aiohttp.FormData()
        data.add_field("reqtype", "fileupload")
        data.add_field(
            "fileToUpload",
            data_source,
            filename=filename,
            content_type=content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream",
        )
        session = await get_shared_http_session()
        async with session.post(
            self.endpoint,
            data=data,
            timeout=timeout,
            headers={"User-Agent": "URLUploadBot/2.0"},
        ) as response:
            body = (await response.text()).strip()
            if response.status >= 400:
                raise ImageHostError(f"HTTP {response.status} ao hospedar a imagem.")
        return _validated_url(body, "O host de imagem nao devolveu uma URL valida.")


class TelegraphUploadHost:
    def __init__(self, endpoint: str = "https://telegra.ph/upload") -> None:
        self.endpoint = endpoint

    async def upload(self, path: Path) -> str:
        with path.open("rb") as image:
            return await self.upload_bytes(path.name, image, mimetypes.guess_type(path.name)[0] or "application/octet-stream")

    async def upload_bytes(self, filename: str, data_source, content_type: str | None = None) -> str:
        timeout = aiohttp.ClientTimeout(total=45, sock_connect=12, sock_read=30)
        data = aiohttp.FormData()
        data.add_field(
            "file",
            data_source,
            filename=filename,
            content_type=content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream",
        )
        session = await get_shared_http_session()
        async with session.post(
            self.endpoint,
            data=data,
            timeout=timeout,
            headers={"User-Agent": "URLUploadBot/2.0"},
        ) as response:
            body = (await response.text()).strip()
            if response.status >= 400:
                raise ImageHostError(f"HTTP {response.status} ao hospedar a imagem.")

        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ImageHostError("O host Telegraph nao devolveu uma resposta valida.") from exc

        if not isinstance(payload, list) or not payload:
            raise ImageHostError("O host Telegraph nao devolveu um link utilizavel.")

        src = str(payload[0].get("src") or "").strip()
        if not src.startswith("/file/"):
            raise ImageHostError("O host Telegraph nao devolveu uma URL valida.")
        return f"https://telegra.ph{src}"


class NullPointerImageHost:
    def __init__(self, endpoint: str = "https://0x0.st") -> None:
        self.endpoint = endpoint

    async def upload(self, path: Path) -> str:
        with path.open("rb") as image:
            return await self.upload_bytes(path.name, image, mimetypes.guess_type(path.name)[0] or "application/octet-stream")

    async def upload_bytes(self, filename: str, data_source, content_type: str | None = None) -> str:
        timeout = aiohttp.ClientTimeout(total=45, sock_connect=12, sock_read=30)
        data = aiohttp.FormData()
        data.add_field(
            "file",
            data_source,
            filename=filename,
            content_type=content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream",
        )
        session = await get_shared_http_session()
        async with session.post(
            self.endpoint,
            data=data,
            timeout=timeout,
            headers={"User-Agent": "URLUploadBot/2.0"},
        ) as response:
            body = (await response.text()).strip()
            if response.status >= 400:
                raise ImageHostError(f"HTTP {response.status} ao hospedar a imagem.")
        return _validated_url(body, "O host 0x0.st nao devolveu uma URL valida.")


class FallbackImageHost:
    def __init__(self) -> None:
        self.providers = [NullPointerImageHost(), CatboxImageHost(), TelegraphUploadHost()]

    async def upload(self, path: Path) -> str:
        failures: list[str] = []
        for provider in self.providers:
            try:
                return await provider.upload(path)
            except Exception as exc:
                failures.append(f"{provider.__class__.__name__}: {exc}")
                continue
        raise ImageHostError(" | ".join(failures) if failures else "Nenhum host de imagem respondeu com sucesso.")

    async def upload_bytes(self, filename: str, payload: bytes, content_type: str | None = None) -> str:
        failures: list[str] = []
        for provider in self.providers:
            try:
                return await provider.upload_bytes(filename, BytesIO(payload), content_type)
            except Exception as exc:
                failures.append(f"{provider.__class__.__name__}: {exc}")
                continue
        raise ImageHostError(" | ".join(failures) if failures else "Nenhum host de imagem respondeu com sucesso.")


TelegraphImageHost = FallbackImageHost


def _validated_url(value: str, message: str) -> str:
    if not value.startswith("https://") and not value.startswith("http://"):
        raise ImageHostError(message)
    return value
