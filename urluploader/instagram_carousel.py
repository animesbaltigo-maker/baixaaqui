from __future__ import annotations

import html as html_lib
import json
import re
import urllib.request
from urllib.parse import urlparse


BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
CDN_SUFFIXES = (".cdninstagram.com", ".fbcdn.net")
MAX_SLIDES = 10


def is_instagram_photo_candidate_url(url: str) -> bool:
    hostname = (urlparse(url).hostname or "").lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    if not (hostname == "instagram.com" or hostname.endswith(".instagram.com")):
        return False
    return bool(re.search(r"/p/[^/?#]+", urlparse(url).path or "", re.IGNORECASE))


def fetch_carousel_images(url: str) -> list[str] | None:
    if not is_instagram_photo_candidate_url(url):
        return None
    shortcode = _extract_shortcode(url)
    candidates: list[str] = []
    if shortcode:
        candidates.extend(
            [
                f"https://www.instagram.com/p/{shortcode}/embed/captioned",
                f"https://www.instagram.com/p/{shortcode}/embed/",
            ]
        )
    candidates.append(url)
    candidates.append(url.replace("instagram.com", "kkinstagram.com"))

    found: list[str] = []
    for candidate in candidates:
        body = _fetch_html(candidate)
        if not body:
            continue
        if _has_video_marker(body):
            return None
        for image_url in _parse_images_from_html(body):
            if image_url not in found:
                found.append(image_url)
        if len(found) >= MAX_SLIDES:
            break
    cdn_images = [item for item in found if _is_instagram_cdn((urlparse(item).hostname or "").lower())]
    return cdn_images[:MAX_SLIDES] if cdn_images else None


def _extract_shortcode(url: str) -> str | None:
    match = re.search(r"/(?:p|reel|reels|tv)/([^/?#]+)", urlparse(url).path or "", re.IGNORECASE)
    return match.group(1) if match else None


def _fetch_html(url: str) -> str | None:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": BROWSER_UA,
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            content_type = (response.headers.get("Content-Type") or "").lower()
            if "html" not in content_type:
                return None
            return response.read(4 * 1024 * 1024).decode("utf-8", errors="ignore")
    except Exception:
        return None


def _parse_images_from_html(body: str) -> list[str]:
    urls: list[str] = []
    for match in re.finditer(r'"display_url"\s*:\s*"((?:[^"\\]|\\.)*)"', body):
        try:
            image_url = json.loads(f'"{match.group(1)}"')
        except json.JSONDecodeError:
            continue
        if image_url and image_url not in urls:
            urls.append(image_url)
    for pattern in (
        r'<meta[^>]*property=["\']og:image["\'][^>]*content=["\']([^"\']*)["\']',
        r'<meta[^>]*content=["\']([^"\']*)["\'][^>]*property=["\']og:image["\']',
        r'<img[^>]+class=["\'][^"\']*EmbeddedMediaImage[^"\']*["\'][^>]+src=["\']([^"\']+)["\']',
    ):
        for match in re.finditer(pattern, body, re.IGNORECASE):
            image_url = html_lib.unescape(match.group(1)).strip()
            if image_url and image_url not in urls:
                urls.append(image_url)
    return urls


def _has_video_marker(body: str) -> bool:
    return bool(
        re.search(r'"video_url"\s*:\s*"', body)
        or re.search(r'"is_video"\s*:\s*true', body)
        or re.search(r'<meta[^>]*property=["\']og:video["\']', body, re.IGNORECASE)
    )


def _is_instagram_cdn(hostname: str) -> bool:
    return bool(hostname) and any(hostname.endswith(suffix) for suffix in CDN_SUFFIXES)
