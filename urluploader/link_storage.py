from __future__ import annotations

import hashlib
import mimetypes
import secrets
import shutil
import time
from io import BytesIO
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from .names import sanitize_filename


@dataclass(frozen=True)
class StoredLink:
    link_id: str
    public_url: str
    internal_path: Path
    filename: str
    mime_type: str | None
    size: int
    sha256: str
    expires_at: int | None


class LocalLinkStorage:
    def __init__(self, root: Path, public_base_url: str, default_ttl_hours: int) -> None:
        self.root = root
        self.public_base_url = public_base_url.rstrip("/")
        self.default_ttl_hours = default_ttl_hours
        self.root.mkdir(parents=True, exist_ok=True)

    async def store(self, path: Path, preferred_name: str | None = None, permanent: bool = False) -> StoredLink:
        filename = sanitize_filename(preferred_name or path.name) or f"arquivo{path.suffix or '.bin'}"
        link_id = secrets.token_urlsafe(10)
        target_dir = self.root / link_id
        target_dir.mkdir(parents=True, exist_ok=False)
        target = target_dir / filename
        await _copy(path, target)
        sha256 = await _sha256(target)
        expires_at = None if permanent else int(time.time() + self.default_ttl_hours * 3600)
        return StoredLink(
            link_id=link_id,
            public_url=f"{self.public_base_url}/{quote(link_id)}/{quote(filename)}",
            internal_path=target,
            filename=filename,
            mime_type=mimetypes.guess_type(filename)[0],
            size=target.stat().st_size,
            sha256=sha256,
            expires_at=expires_at,
        )

    async def store_bytes(
        self,
        payload: bytes,
        preferred_name: str,
        *,
        mime_type: str | None = None,
        ttl_seconds: int | None = None,
    ) -> StoredLink:
        filename = sanitize_filename(preferred_name) or "arquivo.bin"
        link_id = secrets.token_urlsafe(10)
        target_dir = self.root / link_id
        target_dir.mkdir(parents=True, exist_ok=False)
        target = target_dir / filename
        await _write_bytes(target, payload)
        sha256 = await _sha256(target)
        expires_at = int(time.time() + (ttl_seconds if ttl_seconds is not None else self.default_ttl_hours * 3600))
        return StoredLink(
            link_id=link_id,
            public_url=f"{self.public_base_url}/{quote(link_id)}/{quote(filename)}",
            internal_path=target,
            filename=filename,
            mime_type=mime_type or mimetypes.guess_type(filename)[0],
            size=len(payload),
            sha256=sha256,
            expires_at=expires_at,
        )

    def delete(self, internal_path: Path) -> None:
        try:
            if internal_path.exists():
                internal_path.unlink()
            if internal_path.parent != self.root and not any(internal_path.parent.iterdir()):
                internal_path.parent.rmdir()
        except OSError:
            return


async def _copy(source: Path, target: Path) -> None:
    import asyncio

    await asyncio.to_thread(shutil.copy2, source, target)


async def _write_bytes(target: Path, payload: bytes) -> None:
    import asyncio

    def run() -> None:
        target.write_bytes(payload)

    await asyncio.to_thread(run)


async def _sha256(path: Path) -> str:
    import asyncio

    def run() -> str:
        digest = hashlib.sha256()
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    return await asyncio.to_thread(run)
