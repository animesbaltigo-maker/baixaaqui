from __future__ import annotations

import asyncio
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import aiohttp

from .errors import MissingDependencyError, MusicMatchingError, SpotifyNotConfiguredError
from .models import DownloadResult
from .names import sanitize_filename, unique_path


MUSIC_MATCHING_PLATFORMS = {"spotify", "deezer", "apple_music", "tidal", "amazon_music", "shazam"}
DEFAULT_MUSIC_LIMIT = 10


@dataclass(frozen=True)
class MusicTrack:
    id: str
    title: str
    artist: str
    album: str | None = None
    duration: float | None = None
    cover_url: str | None = None
    source_url: str | None = None
    source_platform: str = "music"

    @property
    def display_title(self) -> str:
        if self.artist:
            return f"{self.artist} - {self.title}"
        return self.title


def platform_from_url(url: str) -> str:
    hostname = (urlparse(url).hostname or "").lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    if "spotify" in hostname:
        return "spotify"
    if "deezer" in hostname:
        return "deezer"
    if hostname == "music.apple.com":
        return "apple_music"
    if "tidal" in hostname:
        return "tidal"
    if "music.amazon" in hostname:
        return "amazon_music"
    if "shazam" in hostname:
        return "shazam"
    return "unknown"


def is_music_matching_url(url: str) -> bool:
    return platform_from_url(url) in MUSIC_MATCHING_PLATFORMS


def classify_spotify_url(url: str) -> str:
    path = urlparse(url).path.lower()
    if "/track/" in path:
        return "track"
    if "/album/" in path:
        return "album"
    if "/playlist/" in path:
        return "playlist"
    if "/artist/" in path:
        return "artist"
    return "unknown"


async def inspect_music_url(
    url: str,
    *,
    spotify_client_id: str = "",
    spotify_client_secret: str = "",
    limit: int = DEFAULT_MUSIC_LIMIT,
    proxy: str = "",
    user_agent: str = "",
) -> tuple[MusicTrack, int]:
    tracks = await resolve_music_tracks(
        url,
        spotify_client_id=spotify_client_id,
        spotify_client_secret=spotify_client_secret,
        limit=limit,
        proxy=proxy,
        user_agent=user_agent,
    )
    if not tracks:
        raise MusicMatchingError("Nao consegui identificar a musica desse link.")
    return tracks[0], len(tracks)


async def download_music_url(
    url: str,
    target_dir: Path,
    *,
    max_file_size: int,
    spotify_client_id: str = "",
    spotify_client_secret: str = "",
    limit: int = DEFAULT_MUSIC_LIMIT,
    proxy: str = "",
    user_agent: str = "",
    status=None,
) -> list[DownloadResult]:
    tracks = await resolve_music_tracks(
        url,
        spotify_client_id=spotify_client_id,
        spotify_client_secret=spotify_client_secret,
        limit=limit,
        proxy=proxy,
        user_agent=user_agent,
    )
    if not tracks:
        raise MusicMatchingError("Nao consegui identificar musicas nesse link.")

    results: list[DownloadResult] = []
    total = len(tracks)
    for index, track in enumerate(tracks, start=1):
        if status:
            await status(f"Musica {index}/{total}\n{track.display_title}\nBuscando no YouTube...")
        youtube_url = await find_youtube_match(track, proxy=proxy, user_agent=user_agent)
        if not youtube_url:
            raise MusicMatchingError(f"Musica nao encontrada no YouTube: {track.display_title}")
        if status:
            await status(f"Musica {index}/{total}\n{track.display_title}\nBaixando MP3...")
        file_path = await download_youtube_audio(youtube_url, track, target_dir, max_file_size=max_file_size, proxy=proxy, user_agent=user_agent)
        await write_id3_tags(file_path, track, proxy=proxy, user_agent=user_agent)
        size = file_path.stat().st_size
        if size > max_file_size:
            file_path.unlink(missing_ok=True)
            raise MusicMatchingError("O MP3 ficou maior que o limite configurado.")
        results.append(
            DownloadResult(
                path=file_path,
                filename=file_path.name,
                size=size,
                mime_type="audio/mpeg",
                caption=track.display_title,
            )
        )
    return results


async def resolve_music_tracks(
    url: str,
    *,
    spotify_client_id: str = "",
    spotify_client_secret: str = "",
    limit: int = DEFAULT_MUSIC_LIMIT,
    proxy: str = "",
    user_agent: str = "",
) -> list[MusicTrack]:
    platform = platform_from_url(url)
    limit = max(1, limit)
    if platform == "spotify":
        return await resolve_spotify_tracks(url, spotify_client_id, spotify_client_secret, limit)
    if platform == "deezer":
        return await resolve_deezer_tracks(url, limit=limit, proxy=proxy, user_agent=user_agent)
    if platform == "shazam":
        return [await resolve_shazam_track(url, proxy=proxy, user_agent=user_agent)]
    if platform in {"apple_music", "tidal", "amazon_music"}:
        return [await resolve_generic_music_page(url, platform=platform, proxy=proxy, user_agent=user_agent)]
    return []


async def resolve_spotify_tracks(url: str, client_id: str, client_secret: str, limit: int) -> list[MusicTrack]:
    if not client_id or not client_secret:
        raise SpotifyNotConfiguredError("Configure SPOTIFY_CLIENT_ID e SPOTIFY_CLIENT_SECRET no .env.")
    try:
        import spotipy
        from spotipy.oauth2 import SpotifyClientCredentials
    except ImportError as exc:
        raise MissingDependencyError("Instale spotipy para usar links do Spotify.") from exc

    def load() -> list[MusicTrack]:
        sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(client_id=client_id, client_secret=client_secret))
        kind = classify_spotify_url(url)
        if kind == "track":
            return [_spotify_track_to_music(sp.track(url), source_url=url)]
        if kind == "album":
            album = sp.album(url)
            tracks = album.get("tracks", {}).get("items", [])[:limit]
            return [_spotify_track_to_music({**item, "album": album}, source_url=url) for item in tracks if item]
        if kind == "playlist":
            response = sp.playlist_items(url, limit=limit)
            items = response.get("items", [])
            return [_spotify_track_to_music(item.get("track"), source_url=url) for item in items if item.get("track")]
        if kind == "artist":
            artist_id = url.rstrip("/").split("/")[-1].split("?")[0]
            response = sp.artist_top_tracks(artist_id)
            return [_spotify_track_to_music(item, source_url=url) for item in response.get("tracks", [])[:limit]]
        raise MusicMatchingError("Link Spotify nao reconhecido.")

    return await asyncio.to_thread(load)


def _spotify_track_to_music(track: dict, *, source_url: str) -> MusicTrack:
    album = track.get("album") or {}
    artists = track.get("artists") or []
    artist = ", ".join(item.get("name", "") for item in artists if item.get("name")).strip()
    images = album.get("images") or []
    return MusicTrack(
        id=str(track.get("id") or source_url),
        title=str(track.get("name") or "Spotify track"),
        artist=artist,
        album=album.get("name"),
        duration=(float(track["duration_ms"]) / 1000) if isinstance(track.get("duration_ms"), (int, float)) else None,
        cover_url=images[0].get("url") if images else None,
        source_url=source_url,
        source_platform="spotify",
    )


async def resolve_deezer_tracks(url: str, *, limit: int, proxy: str, user_agent: str) -> list[MusicTrack]:
    path = urlparse(url).path
    track_match = re.search(r"/track/(\d+)", path)
    album_match = re.search(r"/album/(\d+)", path)
    playlist_match = re.search(r"/playlist/(\d+)", path)
    if track_match:
        data = await fetch_json(f"https://api.deezer.com/track/{track_match.group(1)}", proxy=proxy, user_agent=user_agent)
        return [_deezer_track_to_music(data, source_url=url)]
    if album_match:
        data = await fetch_json(f"https://api.deezer.com/album/{album_match.group(1)}", proxy=proxy, user_agent=user_agent)
        album = data.get("title")
        cover = data.get("cover_xl") or data.get("cover_big")
        tracks = data.get("tracks", {}).get("data", [])[:limit]
        return [_deezer_track_to_music(item, source_url=url, album=album, cover_url=cover) for item in tracks]
    if playlist_match:
        data = await fetch_json(f"https://api.deezer.com/playlist/{playlist_match.group(1)}", proxy=proxy, user_agent=user_agent)
        tracks = data.get("tracks", {}).get("data", [])[:limit]
        return [_deezer_track_to_music(item, source_url=url) for item in tracks]
    raise MusicMatchingError("Link Deezer nao reconhecido.")


def _deezer_track_to_music(data: dict, *, source_url: str, album: str | None = None, cover_url: str | None = None) -> MusicTrack:
    artist = data.get("artist") if isinstance(data.get("artist"), dict) else {}
    album_data = data.get("album") if isinstance(data.get("album"), dict) else {}
    return MusicTrack(
        id=str(data.get("id") or source_url),
        title=str(data.get("title") or data.get("title_short") or "Deezer track"),
        artist=str(artist.get("name") or ""),
        album=album or album_data.get("title"),
        duration=float(data["duration"]) if isinstance(data.get("duration"), (int, float)) else None,
        cover_url=cover_url or album_data.get("cover_xl") or album_data.get("cover_big"),
        source_url=source_url,
        source_platform="deezer",
    )


async def resolve_shazam_track(url: str, *, proxy: str, user_agent: str) -> MusicTrack:
    match = re.search(r"/track/(\d+)", url)
    if not match:
        raise MusicMatchingError("ID da faixa Shazam nao encontrado.")
    data = await fetch_json(
        f"https://www.shazam.com/discovery/v5/pt-BR/BR/web/-/track/{match.group(1)}",
        proxy=proxy,
        user_agent=user_agent,
    )
    track = data.get("track") if isinstance(data.get("track"), dict) else data
    images = track.get("images") if isinstance(track.get("images"), dict) else {}
    return MusicTrack(
        id=str(track.get("key") or match.group(1)),
        title=str(track.get("title") or "Shazam track"),
        artist=str(track.get("subtitle") or ""),
        cover_url=images.get("coverarthq") or images.get("coverart"),
        source_url=url,
        source_platform="shazam",
    )


async def resolve_generic_music_page(url: str, *, platform: str, proxy: str, user_agent: str) -> MusicTrack:
    data = await dump_ytdlp_json(url, proxy=proxy, user_agent=user_agent)
    title = _clean_title(str(data.get("title") or data.get("track") or "")) if data else ""
    artist = str(data.get("artist") or data.get("uploader") or "") if data else ""
    duration = float(data["duration"]) if data and isinstance(data.get("duration"), (int, float)) else None
    thumbnail = str(data.get("thumbnail") or "") if data else ""
    if not title:
        og = await fetch_og_metadata(url, proxy=proxy, user_agent=user_agent)
        title = og.get("title", "")
        artist = artist or og.get("artist", "")
        thumbnail = thumbnail or og.get("image", "")
    title, artist = split_title_artist(title, artist)
    if not title:
        raise MusicMatchingError("Nao consegui extrair titulo/artista desse link.")
    return MusicTrack(
        id=url,
        title=title,
        artist=artist,
        duration=duration,
        cover_url=thumbnail or None,
        source_url=url,
        source_platform=platform,
    )


async def find_youtube_match(track: MusicTrack, *, proxy: str, user_agent: str) -> str | None:
    query = f"ytsearch5:{track.title} {track.artist} official audio".strip()
    data = await dump_ytdlp_json(query, proxy=proxy, user_agent=user_agent)
    entries = data.get("entries") if isinstance(data, dict) else None
    candidates = entries if isinstance(entries, list) else []
    if not candidates and isinstance(data, dict):
        candidates = [data]
    best_url = None
    best_delta = None
    for item in candidates:
        if not isinstance(item, dict):
            continue
        url = item.get("webpage_url") or item.get("url")
        if not url:
            continue
        duration = item.get("duration")
        if isinstance(duration, (int, float)) and track.duration:
            delta = abs(float(duration) - track.duration)
            if delta <= 5:
                return str(url)
            if best_delta is None or delta < best_delta:
                best_delta = delta
                best_url = str(url)
        elif best_url is None:
            best_url = str(url)
    return best_url


async def download_youtube_audio(
    youtube_url: str,
    track: MusicTrack,
    target_dir: Path,
    *,
    max_file_size: int,
    proxy: str,
    user_agent: str,
) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    base_name = sanitize_filename(track.display_title, 120) or "musica"
    output_template = str(unique_path(target_dir, f"{base_name}.%(ext)s"))
    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--no-warnings",
        "--no-playlist",
        "--max-filesize",
        str(max_file_size),
        "-f",
        "bestaudio[ext=m4a]/bestaudio[acodec!=none]/bestaudio/best",
        "-x",
        "--audio-format",
        "mp3",
        "--audio-quality",
        "0",
        "-o",
        output_template,
    ]
    if user_agent:
        cmd.extend(["--user-agent", user_agent])
    if proxy:
        cmd.extend(["--proxy", proxy])
    cmd.append(youtube_url)
    process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=900)
    if process.returncode != 0:
        text = stderr.decode("utf-8", errors="replace") or stdout.decode("utf-8", errors="replace")
        raise MusicMatchingError(_last_error_line(text))
    files = sorted(target_dir.glob(f"{base_name}*.mp3"), key=lambda path: path.stat().st_mtime, reverse=True)
    if files:
        return files[0]
    files = sorted(target_dir.glob("*.mp3"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not files:
        raise MusicMatchingError("O yt-dlp nao gerou o MP3.")
    return files[0]


async def write_id3_tags(path: Path, track: MusicTrack, *, proxy: str, user_agent: str) -> None:
    try:
        import eyed3
    except ImportError:
        return
    try:
        audio = eyed3.load(str(path))
        if audio is None:
            return
        if audio.tag is None:
            audio.initTag()
        audio.tag.title = track.title
        audio.tag.artist = track.artist
        if track.album:
            audio.tag.album = track.album
        if track.cover_url:
            cover = await fetch_bytes(track.cover_url, proxy=proxy, user_agent=user_agent)
            if cover:
                audio.tag.images.set(3, cover, "image/jpeg")
        audio.tag.save()
    except Exception:
        return


async def dump_ytdlp_json(url: str, *, proxy: str, user_agent: str) -> dict:
    cmd = [sys.executable, "-m", "yt_dlp", "--dump-single-json", "--skip-download", "--no-warnings", "--no-playlist"]
    if user_agent:
        cmd.extend(["--user-agent", user_agent])
    if proxy:
        cmd.extend(["--proxy", proxy])
    cmd.append(url)
    process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=45)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        return {}
    if process.returncode != 0:
        return {}
    try:
        payload = json.loads(stdout.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


async def fetch_json(url: str, *, proxy: str, user_agent: str) -> dict:
    headers = {"User-Agent": user_agent or "Mozilla/5.0"}
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        async with session.get(url, proxy=proxy or None) as response:
            response.raise_for_status()
            data = await response.json(content_type=None)
    return data if isinstance(data, dict) else {}


async def fetch_bytes(url: str, *, proxy: str, user_agent: str) -> bytes | None:
    headers = {"User-Agent": user_agent or "Mozilla/5.0"}
    timeout = aiohttp.ClientTimeout(total=30)
    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url, proxy=proxy or None) as response:
                if response.status >= 400:
                    return None
                return await response.read()
    except aiohttp.ClientError:
        return None


async def fetch_og_metadata(url: str, *, proxy: str, user_agent: str) -> dict[str, str]:
    headers = {"User-Agent": user_agent or "Mozilla/5.0", "Accept": "text/html,*/*;q=0.8"}
    timeout = aiohttp.ClientTimeout(total=30)
    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url, proxy=proxy or None) as response:
                if response.status >= 400:
                    return {}
                html = await response.text(errors="ignore")
    except aiohttp.ClientError:
        return {}
    return {
        "title": _meta_content(html, "og:title"),
        "artist": _meta_content(html, "music:musician") or _meta_content(html, "og:description"),
        "image": _meta_content(html, "og:image"),
    }


def _meta_content(html: str, property_name: str) -> str:
    pattern = rf'<meta[^>]+property=["\']{re.escape(property_name)}["\'][^>]+content=["\']([^"\']+)["\']'
    match = re.search(pattern, html, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    pattern = rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']{re.escape(property_name)}["\']'
    match = re.search(pattern, html, re.IGNORECASE)
    return match.group(1).strip() if match else ""


def split_title_artist(title: str, artist: str) -> tuple[str, str]:
    cleaned = _clean_title(title)
    if artist or " - " not in cleaned:
        return cleaned, artist
    left, right = cleaned.split(" - ", 1)
    return right.strip() or cleaned, left.strip()


def _clean_title(title: str) -> str:
    return re.sub(r"\s+", " ", title.replace("|", " - ")).strip()


def _last_error_line(text: str) -> str:
    lines = [line.replace("ERROR:", "").strip() for line in text.splitlines() if line.strip()]
    return (lines[-1] if lines else "Falha ao baixar audio.")[:240]
