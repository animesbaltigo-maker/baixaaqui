from __future__ import annotations

import re
from html import unescape
from email.message import Message
from pathlib import Path
from typing import Mapping
from urllib.parse import parse_qs, parse_qsl, unquote, urlencode, urlparse, urlunparse

from .models import UploadMode, UploadRequest


URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
TRAILING_URL_PUNCT = ".,;:!?)\"'>]}"
TRACKING_PARAM_NAMES = {"si", "feature", "ref"}
INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED_WINDOWS_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "COM1",
    "COM2",
    "COM3",
    "COM4",
    "COM5",
    "COM6",
    "COM7",
    "COM8",
    "COM9",
    "LPT1",
    "LPT2",
    "LPT3",
    "LPT4",
    "LPT5",
    "LPT6",
    "LPT7",
    "LPT8",
    "LPT9",
}
VIDEO_EXTENSIONS = {
    ".3gp",
    ".avi",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".webm",
}
AUDIO_EXTENSIONS = {
    ".aac",
    ".flac",
    ".m4a",
    ".mp3",
    ".ogg",
    ".opus",
    ".wav",
}
SOCIAL_DOMAINS = {
    "crunchyroll.com",
    "facebook.com",
    "fb.watch",
    "instagram.com",
    "likee.video",
    "pinterest.com",
    "pin.it",
    "reddit.com",
    "redd.it",
    "soundcloud.com",
    "spotify.com",
    "threads.net",
    "tiktok.com",
    "twitch.tv",
    "twitter.com",
    "vimeo.com",
    "vk.com",
    "x.com",
    "youtube.com",
    "youtu.be",
    "kwai.com",
    "kw.ai",
}


def sanitize_filename(filename: str | None, max_length: int = 180) -> str | None:
    if not filename:
        return None

    name = unquote(filename).strip().strip("\"'")
    name = Path(name).name
    name = INVALID_FILENAME_CHARS.sub("_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")

    if not name:
        return None

    stem = Path(name).stem
    suffix = Path(name).suffix
    if stem.upper() in RESERVED_WINDOWS_NAMES:
        name = f"_{name}"

    if len(name) <= max_length:
        return name

    suffix = suffix[:30]
    stem_limit = max_length - len(suffix)
    return f"{Path(name).stem[:stem_limit]}{suffix}"


def normalize_mode(value: str | None, default: UploadMode | None = "auto") -> UploadMode | None:
    if not value:
        return default

    normalized = value.strip().lower()
    if normalized in {"auto", "automatic", "automatico", "automático"}:
        return "auto"
    if normalized in {"document", "doc", "file", "arquivo", "documento", "document"}:
        return "document"
    if normalized in {"photo", "foto", "image", "imagem", "img"}:
        return "photo"
    if normalized in {"video", "vídeo", "stream"}:
        return "video"
    if normalized in {"audio", "áudio", "mp3", "music", "musica", "música"}:
        return "audio"
    return default


def parse_upload_request(raw_text: str, default_mode: UploadMode) -> UploadRequest | None:
    text = raw_text.strip()
    if text.lower().startswith("/upload"):
        parts = text.split(maxsplit=1)
        text = parts[1].strip() if len(parts) == 2 else ""

    if not text:
        return None

    chunks = [chunk.strip() for chunk in text.split("|")]
    match = URL_RE.search(chunks[0])
    if not match:
        return None

    url = match.group(0).rstrip(".,)>]")
    filename = sanitize_filename(chunks[1]) if len(chunks) > 1 else None
    mode = default_mode
    caption = None
    if len(chunks) > 2:
        parsed_mode = normalize_mode(chunks[2], None)
        if parsed_mode:
            mode = parsed_mode
            caption = " | ".join(chunks[3:]).strip() or None
        else:
            caption = " | ".join(chunks[2:]).strip() or None

    return UploadRequest(url=url, filename=filename, mode=mode, caption=caption)


def filename_from_headers(headers: Mapping[str, str]) -> str | None:
    content_disposition = headers.get("Content-Disposition") or headers.get("content-disposition")
    if not content_disposition:
        return None

    message = Message()
    message["content-disposition"] = content_disposition
    return sanitize_filename(message.get_filename())


def filename_from_url(url: str) -> str | None:
    path = urlparse(url).path
    if not path:
        return None
    return sanitize_filename(Path(unquote(path)).name)


def contains_url(text: str) -> bool:
    return bool(URL_RE.search(text))


def extract_url(text: str) -> str | None:
    match = URL_RE.search(text)
    if not match:
        return None
    url = match.group(0)
    while url and url[-1] in TRAILING_URL_PUNCT:
        url = url[:-1]
    return normalize_shared_url(url)


def normalize_shared_url(url: str) -> str:
    raw = unescape(url.strip())
    parsed = urlparse(raw)
    hostname = (parsed.hostname or "").lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    query = parse_qs(parsed.query)

    if hostname in {"facebook.com", "m.facebook.com"} and parsed.path.startswith("/login"):
        next_url = query.get("next", [None])[0]
        if next_url:
            return normalize_shared_url(unquote(next_url))

    if hostname in {"l.facebook.com", "lm.facebook.com"} and parsed.path.startswith("/l.php"):
        target_url = query.get("u", [None])[0]
        if target_url:
            return normalize_shared_url(unquote(target_url))

    if parsed.query:
        filtered_query = urlencode(
            [
                (name, value)
                for name, value in parse_qsl(parsed.query, keep_blank_values=True)
                if not (name.lower().startswith("utm_") or name.lower() in TRACKING_PARAM_NAMES)
            ]
        )
        parsed = parsed._replace(query=filtered_query)
        raw = urlunparse(parsed)

    return raw


def is_social_url(url: str) -> bool:
    hostname = (urlparse(url).hostname or "").lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    return any(hostname == domain or hostname.endswith(f".{domain}") for domain in SOCIAL_DOMAINS)


def choose_filename(url: str, headers: Mapping[str, str], preferred: str | None) -> str:
    return (
        sanitize_filename(preferred)
        or filename_from_headers(headers)
        or filename_from_url(url)
        or "download.bin"
    )


def is_video_filename(filename: str) -> bool:
    return Path(filename).suffix.lower() in VIDEO_EXTENSIONS


def is_audio_filename(filename: str) -> bool:
    return Path(filename).suffix.lower() in AUDIO_EXTENSIONS


def unique_path(directory: Path, filename: str) -> Path:
    path = directory / filename
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    counter = 2
    while True:
        candidate = directory / f"{stem} ({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1
