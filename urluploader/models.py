from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal


UploadMode = Literal["auto", "document", "video", "audio", "photo"]
SourceType = Literal["direct_url", "social_url", "telegram_file"]


@dataclass(frozen=True)
class UploadRequest:
    url: str
    filename: str | None
    mode: UploadMode
    caption: str | None = None


@dataclass(frozen=True)
class JobRequest:
    user_id: int
    chat_id: int
    source_type: SourceType
    mode: UploadMode
    filename: str | None = None
    caption: str | None = None
    url: str | None = None
    source_message_id: int | None = None
    reply_to_message_id: int | None = None


@dataclass(frozen=True)
class DownloadResult:
    path: Path
    filename: str
    size: int
    mime_type: str | None
    caption: str | None = None


@dataclass(frozen=True)
class RemoteFileInfo:
    url: str
    filename: str
    size: int | None
    mime_type: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "RemoteFileInfo":
        size = data.get("size")
        return cls(
            url=str(data.get("url") or ""),
            filename=str(data.get("filename") or "download.bin"),
            size=int(size) if isinstance(size, int) else None,
            mime_type=data.get("mime_type") if isinstance(data.get("mime_type"), str) else None,
        )
