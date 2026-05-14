from __future__ import annotations

import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


COOKIE_HEADER_PREFIXES = ("# Netscape HTTP Cookie File", "# HTTP Cookie File")
PLATFORM_COOKIE_ENV = {
    "youtube": "YTDLP_COOKIES_YOUTUBE",
    "instagram": "YTDLP_COOKIES_INSTAGRAM",
    "tiktok": "YTDLP_COOKIES_TIKTOK",
    "x": "YTDLP_COOKIES_TWITTER",
    "twitter": "YTDLP_COOKIES_TWITTER",
    "facebook": "YTDLP_COOKIES_FACEBOOK",
    "crunchyroll": "YTDLP_COOKIES_CRUNCHYROLL",
}


@dataclass(frozen=True)
class CookieStatus:
    platform: str
    env_name: str
    path: str
    exists: bool
    readable: bool
    valid_netscape: bool
    secure_permissions: bool
    age_hours: float | None
    warning: str | None = None

    @property
    def usable(self) -> bool:
        return self.exists and self.readable and self.valid_netscape


def platform_from_url(url: str) -> str:
    hostname = (urlparse(url).hostname or "").lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    if "youtu" in hostname:
        return "youtube"
    if "instagram" in hostname:
        return "instagram"
    if "tiktok" in hostname:
        return "tiktok"
    if hostname in {"x.com", "twitter.com"}:
        return "x"
    if "facebook" in hostname or hostname == "fb.watch":
        return "facebook"
    if "crunchyroll" in hostname:
        return "crunchyroll"
    return hostname.split(".")[-2] if "." in hostname else hostname or "unknown"


def resolve_platform_cookie_file(url: str, default_cookie_file: str, platform_files: dict[str, str]) -> str:
    platform = platform_from_url(url)
    path = (platform_files.get(platform) or "").strip()
    return path or default_cookie_file.strip()


def inspect_cookie_file(path: str, platform: str, env_name: str, max_age_hours: int) -> CookieStatus:
    cleaned = path.strip()
    if not cleaned:
        return CookieStatus(platform, env_name, "", False, False, False, False, None, "not configured")
    cookie_path = Path(cleaned).expanduser()
    exists = cookie_path.exists()
    readable = False
    valid = False
    secure = True
    age_hours: float | None = None
    warning = None
    if exists:
        try:
            with cookie_path.open("r", encoding="utf-8", errors="replace") as file:
                head = [file.readline().strip() for _ in range(5)]
            readable = True
            valid = any(line.startswith(COOKIE_HEADER_PREFIXES) for line in head) or any(
                len(line.split("\t")) >= 7 for line in head if line and not line.startswith("#")
            )
        except OSError as exc:
            warning = f"not readable: {exc}"
        try:
            mode = stat.S_IMODE(cookie_path.stat().st_mode)
            if os.name != "nt":
                secure = mode & (stat.S_IRWXG | stat.S_IRWXO) == 0
            age_hours = max(0.0, (time.time() - cookie_path.stat().st_mtime) / 3600)
            if age_hours > max_age_hours:
                warning = f"older than {max_age_hours}h"
        except OSError as exc:
            warning = warning or f"stat failed: {exc}"
    else:
        warning = "file not found"
    if exists and readable and not valid:
        warning = "not a Netscape/Mozilla cookies.txt file"
    if exists and readable and valid and not secure:
        warning = "permissions should be chmod 600"
    return CookieStatus(platform, env_name, str(cookie_path), exists, readable, valid, secure, age_hours, warning)


def inspect_all_cookies(
    default_cookie_file: str,
    platform_files: dict[str, str],
    max_age_hours: int,
) -> list[CookieStatus]:
    statuses: list[CookieStatus] = []
    if default_cookie_file.strip():
        statuses.append(inspect_cookie_file(default_cookie_file, "default", "YTDLP_COOKIES_FILE", max_age_hours))
    for platform, env_name in PLATFORM_COOKIE_ENV.items():
        path = (platform_files.get(platform) or "").strip()
        if path:
            statuses.append(inspect_cookie_file(path, platform, env_name, max_age_hours))
    return statuses
