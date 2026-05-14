from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from urllib.parse import urlparse

from .models import RemoteFileInfo
from .names import is_audio_filename, is_video_filename
from .social import SocialInfo


@dataclass(frozen=True)
class ContentProfile:
    source: str
    kind: str
    platform: str
    item_count: int = 1
    mime_type: str | None = None
    title: str | None = None
    can_send_photo: bool = False
    can_send_video: bool = False
    can_send_audio: bool = False
    can_send_document: bool = True
    can_generate_link: bool = False
    can_set_thumb: bool = False
    can_rename: bool = True
    can_edit_caption: bool = True
    can_choose_quality: bool = False
    can_extract_audio: bool = False

    @property
    def is_collection(self) -> bool:
        return self.item_count > 1 or self.kind == "album"


def platform_from_url(url: str | None) -> str:
    hostname = (urlparse(url or "").hostname or "").lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    if "youtu" in hostname:
        return "youtube"
    if "instagram" in hostname:
        return "instagram"
    if hostname in {"x.com", "twitter.com"}:
        return "x"
    if "facebook" in hostname or hostname == "fb.watch":
        return "facebook"
    if "reddit" in hostname or hostname == "redd.it":
        return "reddit"
    if "pinterest" in hostname or hostname == "pin.it":
        return "pinterest"
    if "tiktok" in hostname:
        return "tiktok"
    if "crunchyroll" in hostname:
        return "crunchyroll"
    if "soundcloud" in hostname:
        return "soundcloud"
    if "spotify" in hostname:
        return "spotify"
    if "twitch" in hostname:
        return "twitch"
    if "kwai" in hostname or hostname == "kw.ai":
        return "kwai"
    if "threads.net" in hostname:
        return "threads"
    return hostname or "direct"


def media_kind_from_name(filename: str | None, mime_type: str | None = None) -> str:
    mime = (mime_type or mimetypes.guess_type(filename or "")[0] or "").lower()
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("video/") or is_video_filename(filename or ""):
        return "video"
    if mime.startswith("audio/") or is_audio_filename(filename or ""):
        return "audio"
    return "document"


def profile_for_direct(info: RemoteFileInfo) -> ContentProfile:
    kind = media_kind_from_name(info.filename, info.mime_type)
    return ContentProfile(
        source="direct",
        kind=kind,
        platform=platform_from_url(info.url),
        mime_type=info.mime_type,
        title=info.filename,
        can_send_photo=kind == "image",
        can_send_video=kind == "video",
        can_send_audio=kind == "audio",
        can_send_document=True,
        can_generate_link=kind == "image",
        can_set_thumb=kind in {"video", "document"},
    )


def profile_for_social(info: SocialInfo) -> ContentProfile:
    raw_kind = (info.media_type or "").lower()
    item_kinds = {item.kind for item in info.media_items}
    if info.item_count > 1:
        kind = "album"
    elif "audio" in raw_kind or "audio" in item_kinds:
        kind = "audio"
    elif "image" in raw_kind or "image" in item_kinds:
        kind = "image"
    else:
        kind = "video"
    return ContentProfile(
        source="social",
        kind=kind,
        platform=platform_from_url(info.url),
        item_count=info.item_count,
        title=info.title,
        can_send_photo=kind == "image",
        can_send_video=kind == "video",
        can_send_audio=kind == "audio",
        can_send_document=True,
        can_generate_link=kind == "image" and info.item_count == 1,
        can_set_thumb=False,
        can_choose_quality=kind == "video" and bool(info.qualities),
        can_extract_audio=kind == "video",
    )


def profile_for_telegram(filename: str, mime_type: str | None, *, is_image_message: bool) -> ContentProfile:
    kind = "image" if is_image_message else media_kind_from_name(filename, mime_type)
    return ContentProfile(
        source="telegram",
        kind=kind,
        platform="telegram",
        mime_type=mime_type,
        title=filename,
        can_send_photo=kind == "image",
        can_send_video=kind == "video",
        can_send_audio=kind == "audio",
        can_send_document=True,
        can_generate_link=kind == "image",
        can_set_thumb=kind in {"video", "document"},
    )
