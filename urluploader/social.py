from __future__ import annotations

import asyncio
import json
import mimetypes
import re
import shutil
import subprocess
import sys
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .media_probe import MediaProbe
from .models import DownloadResult, UploadMode
from .names import sanitize_filename, unique_path
from .progress import human_size
from .cookies import inspect_cookie_file, resolve_platform_cookie_file
from .errors import BaixaAquiError, CookieRequiredError, DownloadTimeoutError, PlatformBlockedError


class SocialDownloadError(BaixaAquiError):
    """Raised when a social-media URL cannot be processed."""


class MissingYtDlpError(SocialDownloadError):
    """Raised when yt-dlp is not available in the current Python env."""


StatusCallback = Callable[[str], Awaitable[None]]


@dataclass(frozen=True)
class SocialMediaItem:
    url: str
    filename: str
    mime_type: str | None = None
    kind: str = "file"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "SocialMediaItem":
        return cls(
            url=str(data.get("url") or ""),
            filename=str(data.get("filename") or "media.bin"),
            mime_type=data.get("mime_type") if isinstance(data.get("mime_type"), str) else None,
            kind=str(data.get("kind") or "file"),
        )


@dataclass(frozen=True)
class SocialInfo:
    url: str
    title: str | None
    author: str | None
    duration: float | None
    media_type: str
    item_count: int
    quality: str | None
    description: str | None
    thumbnail: str | None
    qualities: tuple[int, ...] = ()
    provider: str = "yt_dlp"
    media_items: tuple[SocialMediaItem, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "SocialInfo":
        raw_qualities = data.get("qualities", [])
        qualities = tuple(int(item) for item in raw_qualities if isinstance(item, int)) if isinstance(raw_qualities, list) else ()
        raw_items = data.get("media_items", [])
        media_items = (
            tuple(SocialMediaItem.from_dict(item) for item in raw_items if isinstance(item, dict))
            if isinstance(raw_items, (list, tuple))
            else ()
        )
        return cls(
            url=str(data.get("url") or ""),
            title=data.get("title") if isinstance(data.get("title"), str) else None,
            author=data.get("author") if isinstance(data.get("author"), str) else None,
            duration=float(data["duration"]) if isinstance(data.get("duration"), (int, float)) else None,
            media_type=str(data.get("media_type") or "media"),
            item_count=int(data.get("item_count") or 1),
            quality=data.get("quality") if isinstance(data.get("quality"), str) else None,
            description=data.get("description") if isinstance(data.get("description"), str) else None,
            thumbnail=data.get("thumbnail") if isinstance(data.get("thumbnail"), str) else None,
            qualities=qualities,
            provider=str(data.get("provider") or "yt_dlp"),
            media_items=media_items,
        )


class SocialDownloader:
    def __init__(
        self,
        max_file_size: int,
        ytdlp_format: str,
        *,
        cookies_file: str = "",
        cookies_from_browser: str = "",
        extractor_args: str = "",
        user_agent: str = "",
        platform_cookies: dict[str, str] | None = None,
        cookies_max_age_hours: int = 72,
        concurrent_fragments: int = 4,
        aria2_connections: int = 8,
        aria2_split: int = 8,
        aria2_min_split_size: str = "1M",
        gallery_config: str = "",
    ) -> None:
        self.max_file_size = max_file_size
        self.ytdlp_format = ytdlp_format
        self.cookies_file = cookies_file.strip()
        self.cookies_from_browser = cookies_from_browser.strip()
        self.extractor_args = extractor_args.strip()
        self.user_agent = user_agent.strip()
        self.platform_cookies = platform_cookies or {}
        self.cookies_max_age_hours = cookies_max_age_hours
        self.concurrent_fragments = max(1, concurrent_fragments)
        self.aria2_connections = max(1, aria2_connections)
        self.aria2_split = max(1, aria2_split)
        self.aria2_min_split_size = aria2_min_split_size
        self.gallery_config = gallery_config.strip()
        self.ffmpeg = _find_ffmpeg()
        self.ffprobe = _find_ffprobe(self.ffmpeg)
        self.can_postprocess = bool(self.ffmpeg and self.ffprobe)
        self.aria2c = shutil.which("aria2c")

    async def inspect(self, url: str) -> SocialInfo:
        data: dict[str, object] | None
        output: str
        data, output = await self._dump_ytdlp_json(url, use_cookies=True)
        if data is None and _platform_from_url(url) == "instagram" and _is_auth_error(output):
            data, output = await self._dump_ytdlp_json(url, use_cookies=False)
        if data is None:
            if _should_try_gallery_dl(url, output):
                try:
                    return await self._inspect_with_gallery_dl(url)
                except SocialDownloadError:
                    pass
            raise _typed_social_error(url, output)

        entries = data.get("entries") or []
        item_count = len(entries) if isinstance(entries, list) and entries else 1
        sample = entries[0] if isinstance(entries, list) and entries else data
        formats = sample.get("formats") if isinstance(sample, dict) else None
        format_list = formats if isinstance(formats, list) else []
        quality = _best_quality(format_list)
        qualities = _quality_list(format_list)
        media_type = _media_type(sample if isinstance(sample, dict) else data, item_count)
        info = SocialInfo(
            url=url,
            title=_clean_text(data.get("title") or sample.get("title")),
            author=_clean_text(data.get("uploader") or data.get("channel") or sample.get("uploader")),
            duration=_float_or_none(data.get("duration") or sample.get("duration")),
            media_type=media_type,
            item_count=item_count,
            quality=quality,
            description=_clean_text(data.get("description") or sample.get("description"), 1000),
            thumbnail=_clean_text(data.get("thumbnail") or sample.get("thumbnail")),
            qualities=tuple(qualities),
            provider="yt_dlp",
        )
        if _should_refine_with_gallery(url, data, info):
            try:
                return await self._inspect_with_gallery_dl(url)
            except SocialDownloadError:
                return info
        return info

    async def _dump_ytdlp_json(self, url: str, *, use_cookies: bool = True) -> tuple[dict[str, object] | None, str]:
        cmd = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--dump-single-json",
            "--skip-download",
            "--no-warnings",
            "--no-playlist",
        ]
        cmd.extend(self._common_args(url, use_cookies=use_cookies))
        cmd.append(url)
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=45)
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.wait()
            raise DownloadTimeoutError("A plataforma demorou demais para responder.") from exc
        if process.returncode != 0:
            output = stderr.decode("utf-8", errors="replace").strip()
            if "No module named yt_dlp" in output:
                raise MissingYtDlpError("O yt-dlp nao esta instalado.")
            return None, output

        try:
            data = json.loads(stdout.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            raise SocialDownloadError("Nao consegui ler os metadados dessa midia.") from exc
        if not isinstance(data, dict):
            raise SocialDownloadError("Nao consegui ler os metadados dessa midia.")
        return data, ""

    async def download(
        self,
        url: str,
        target_dir: Path,
        preferred_filename: str | None,
        mode: UploadMode,
        status: StatusCallback | None = None,
        format_selector: str | None = None,
        prefetched_info: SocialInfo | None = None,
    ) -> list[DownloadResult]:
        if prefetched_info and prefetched_info.provider == "gallery_dl" and prefetched_info.media_items:
            return await self._download_gallery_media(prefetched_info, target_dir, preferred_filename, mode, status)

        before = {path.resolve() for path in target_dir.rglob("*") if path.is_file()}
        cmd = self._build_command(url, target_dir, mode, format_selector)
        return_code, output = await self._run_ytdlp_download(cmd, status)

        if "No module named yt_dlp" in output:
            raise MissingYtDlpError("O yt-dlp nao esta instalado.")
        if return_code != 0:
            if _platform_from_url(url) == "instagram":
                recovered = await self._recover_instagram_download(
                    url,
                    target_dir,
                    before,
                    preferred_filename,
                    mode,
                    status,
                )
                if recovered:
                    return recovered
            if _should_try_gallery_dl(url, output):
                try:
                    info = await self._inspect_with_gallery_dl(url)
                    return await self._download_gallery_media(info, target_dir, preferred_filename, mode, status)
                except SocialDownloadError:
                    pass
            raise _typed_social_error(url, output) or SocialDownloadError(f"O yt-dlp encerrou com codigo {return_code}.")

        files = _new_media_files(target_dir, before)
        if not files:
            if _platform_from_url(url) in {"instagram", "facebook", "x", "tiktok"}:
                try:
                    info = await self._inspect_with_gallery_dl(url)
                    return await self._download_gallery_media(info, target_dir, preferred_filename, mode, status)
                except SocialDownloadError:
                    if _platform_from_url(url) == "instagram":
                        recovered = await self._recover_instagram_download(
                            url,
                            target_dir,
                            before,
                            preferred_filename,
                            mode,
                            status,
                        )
                        if recovered:
                            return recovered
            raise SocialDownloadError("Nenhum arquivo de midia foi gerado.")

        return await self._results_from_files(target_dir, files, preferred_filename, mode)

    async def _run_ytdlp_download(self, cmd: list[str], status: StatusCallback | None) -> tuple[int, str]:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        tail: list[str] = []
        try:
            assert process.stdout is not None
            while True:
                raw_line = await process.stdout.readline()
                if not raw_line:
                    break

                line = raw_line.decode("utf-8", errors="replace").strip()
                if line:
                    tail.append(line)
                    tail = tail[-8:]
                    if status:
                        progress = _clean_progress(line) or _clean_external_progress(line)
                        if progress:
                            await status(progress)

            return_code = await asyncio.wait_for(process.wait(), timeout=max(300, self.max_file_size // (256 * 1024)))
        except asyncio.CancelledError:
            process.kill()
            await process.wait()
            raise
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.wait()
            raise DownloadTimeoutError("O download demorou demais e foi interrompido com seguranca.") from exc
        return return_code, "\n".join(tail)

    async def _recover_instagram_download(
        self,
        url: str,
        target_dir: Path,
        before: set[Path],
        preferred_filename: str | None,
        mode: UploadMode,
        status: StatusCallback | None,
    ) -> list[DownloadResult] | None:
        gallery_mode: UploadMode = "auto" if mode == "video" else mode
        try:
            info = await self._inspect_with_gallery_dl(url)
            return await self._download_gallery_media(info, target_dir, preferred_filename, gallery_mode, status)
        except SocialDownloadError:
            pass

        attempts: list[tuple[UploadMode, str | None, bool]] = [
            ("auto" if mode == "video" else mode, None, False),
            ("auto", "best[ext=mp4]/best", False),
            ("auto" if mode == "video" else mode, None, True),
        ]
        for attempt_mode, selector, use_cookies in attempts:
            cmd = self._build_command(url, target_dir, attempt_mode, selector, use_cookies=use_cookies)
            return_code, output = await self._run_ytdlp_download(cmd, status)
            if "No module named yt_dlp" in output:
                raise MissingYtDlpError("O yt-dlp nao esta instalado.")
            if return_code != 0:
                continue
            files = _new_media_files(target_dir, before)
            if files:
                return await self._results_from_files(target_dir, files, preferred_filename, attempt_mode)
        return None

    async def _results_from_files(
        self,
        target_dir: Path,
        files: list[Path],
        preferred_filename: str | None,
        mode: UploadMode,
    ) -> list[DownloadResult]:
        metadata_caption = self._read_caption(target_dir)
        files.sort(key=lambda path: path.stat().st_mtime)
        files = await self._coalesce_media_files(files, target_dir, mode)
        if preferred_filename and len(files) == 1:
            files[0] = self._rename(files[0], preferred_filename)

        results: list[DownloadResult] = []
        for path in files:
            size = path.stat().st_size
            if size > self.max_file_size:
                raise SocialDownloadError(
                    f"O arquivo baixado e muito grande: {human_size(size)}. Limite: {human_size(self.max_file_size)}."
                )
            mime_type = mimetypes.guess_type(path.name)[0]
            results.append(
                DownloadResult(
                    path=path,
                    filename=path.name,
                    size=size,
                    mime_type=mime_type,
                    caption=metadata_caption,
                )
            )
        return results

    async def _inspect_with_gallery_dl(self, url: str) -> SocialInfo:
        payload = await self._run_gallery_dl(url)
        metadata, media_items, gallery_types = _parse_gallery_payload(url, payload)
        primary_items = [item for item in media_items if item.kind != "audio"] or list(media_items)
        item_count = len(primary_items) or len(media_items) or 1
        media_type = _gallery_media_type(primary_items or media_items, gallery_types)
        return SocialInfo(
            url=url,
            title=_clean_text(metadata.get("title") or metadata.get("content") or metadata.get("desc")),
            author=_clean_text(_gallery_author(metadata)),
            duration=_float_or_none(metadata.get("duration")) if media_type == "video" else None,
            media_type=media_type,
            item_count=item_count,
            quality=None,
            description=_clean_text(metadata.get("content") or metadata.get("desc") or metadata.get("title"), 1000),
            thumbnail=_clean_text(_gallery_thumbnail(metadata)),
            qualities=(),
            provider="gallery_dl",
            media_items=tuple(media_items),
        )

    async def _run_gallery_dl(self, url: str) -> list[object]:
        cmd = [sys.executable, "-m", "gallery_dl", "-J", "--no-input"]
        cmd.extend(self._gallery_common_args(url))
        cmd.append(url)
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=60)
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.wait()
            raise DownloadTimeoutError("O fallback da plataforma demorou demais para responder.") from exc
        stderr_text = stderr.decode("utf-8", errors="replace").strip()
        if process.returncode != 0:
            if "No module named gallery_dl" in stderr_text:
                raise SocialDownloadError("O fallback de imagem nao esta disponivel neste servidor.")
            raise SocialDownloadError(_friendly_gallery_error(url, stderr_text))
        try:
            payload = json.loads(stdout.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            raise SocialDownloadError("Nao consegui ler a resposta alternativa dessa plataforma.") from exc
        if not isinstance(payload, list):
            raise SocialDownloadError("A plataforma nao devolveu uma resposta valida.")
        return payload

    def _build_command(
        self,
        url: str,
        target_dir: Path,
        mode: UploadMode,
        format_selector: str | None = None,
        *,
        use_cookies: bool = True,
    ) -> list[str]:
        template = "%(title).180B [%(id)s].%(ext)s"
        cmd = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--newline",
            "--no-warnings",
            "--restrict-filenames",
            "--no-playlist",
            "--concurrent-fragments",
            str(self.concurrent_fragments),
            "--retries",
            "5",
            "--fragment-retries",
            "5",
            "--file-access-retries",
            "5",
            "--socket-timeout",
            "20",
            "--buffer-size",
            "64K",
            "--http-chunk-size",
            "10M",
            "--max-filesize",
            str(self.max_file_size),
            "--paths",
            str(target_dir),
            "-o",
            template,
        ]
        cmd.extend(self._common_args(url, use_cookies=use_cookies))
        if self.can_postprocess and self.ffmpeg:
            cmd.extend(["--ffmpeg-location", str(Path(self.ffmpeg).parent)])
        if self.aria2c:
            cmd.extend(
                [
                    "--downloader",
                    "http,https,ftp,ftps:aria2c",
                    "--downloader",
                    "dash,m3u8:native",
                    "--downloader-args",
                    (
                        f"aria2c:-c -x{self.aria2_connections} -s{self.aria2_split} "
                        f"-k1M --min-split-size={self.aria2_min_split_size} "
                        "--file-allocation=none --summary-interval=1 --max-tries=3 --retry-wait=3"
                    ),
                ]
            )

        if mode == "audio" or _platform_from_url(url) == "youtube_music":
            if self.can_postprocess:
                cmd.extend(["-f", "bestaudio[ext=m4a]/bestaudio[acodec!=none]/bestaudio/best", "-x", "--audio-format", "mp3"])
            else:
                cmd.extend(["-f", "bestaudio[ext=m4a]/bestaudio[acodec!=none]/bestaudio/best"])
        else:
            selector = format_selector or self.ytdlp_format
            if self.can_postprocess:
                cmd.extend(["-f", selector, "--merge-output-format", "mp4"])
            else:
                cmd.extend(["-f", _progressive_only_selector(selector)])

        cmd.append(url)
        return cmd

    def _cookie_args(self, url: str) -> list[str]:
        args: list[str] = []
        cookie_file = resolve_platform_cookie_file(url, self.cookies_file, self.platform_cookies)
        if cookie_file:
            platform = _platform_from_url(url)
            status = inspect_cookie_file(cookie_file, platform, "cookies", self.cookies_max_age_hours)
            if status.usable:
                args.extend(["--cookies", status.path])
            return args
        if self.cookies_from_browser:
            args.extend(["--cookies-from-browser", self.cookies_from_browser])
        return args

    def _common_args(self, url: str = "", *, use_cookies: bool = True) -> list[str]:
        args: list[str] = []
        if self.user_agent:
            args.extend(["--user-agent", self.user_agent])
        if self.extractor_args:
            args.extend(["--extractor-args", self.extractor_args])
        if use_cookies:
            args.extend(self._cookie_args(url))
        return args

    def _gallery_common_args(self, url: str = "") -> list[str]:
        args: list[str] = []
        if self.gallery_config:
            args.extend(["--config", self.gallery_config])
        if self.user_agent:
            args.extend(["--user-agent", self.user_agent])
        args.extend(self._cookie_args(url))
        return args

    async def _download_gallery_media(
        self,
        info: SocialInfo,
        target_dir: Path,
        preferred_filename: str | None,
        mode: UploadMode,
        status: StatusCallback | None,
    ) -> list[DownloadResult]:
        items = _select_gallery_items(info, mode)
        if not items:
            raise SocialDownloadError("Nao encontrei midia compativel para esta acao.")
        before = {path.resolve() for path in target_dir.rglob("*") if path.is_file()}
        desired_kinds = {item.kind for item in items if item.kind != "file"} or {item.kind for item in items}
        total_items = max(len(items), 1)
        cmd = [
            sys.executable,
            "-m",
            "gallery_dl",
            "--no-input",
            "--quiet",
            "--no-skip",
            "--retries",
            "4",
            "--http-timeout",
            "30",
            "--filesize-max",
            str(self.max_file_size),
            "--directory",
            str(target_dir),
            "--Print",
            "download:{filename}.{extension}",
        ]
        cmd.extend(self._gallery_common_args(info.url))
        cmd.append(info.url)
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        done = 0
        tail: list[str] = []
        try:
            assert process.stdout is not None
            while True:
                raw_line = await process.stdout.readline()
                if not raw_line:
                    break
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                tail.append(line)
                tail = tail[-8:]
                done = min(done + 1, total_items)
                if status:
                    await status(_gallery_download_text(done, total_items, line))
            stderr = await process.stderr.read() if process.stderr else b""
            return_code = await asyncio.wait_for(process.wait(), timeout=max(180, self.max_file_size // (256 * 1024)))
        except asyncio.CancelledError:
            process.kill()
            await process.wait()
            raise
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.wait()
            raise DownloadTimeoutError("O download alternativo demorou demais e foi interrompido.") from exc

        stderr_text = stderr.decode("utf-8", errors="replace").strip()
        if return_code != 0:
            raise SocialDownloadError(_friendly_gallery_error(info.url, stderr_text or "\n".join(tail)))

        files = _new_media_files(target_dir, before)
        files = _filter_gallery_files(files, desired_kinds) or files
        if not files:
            raise SocialDownloadError("Nenhum arquivo de midia foi gerado.")

        if preferred_filename and len(files) == 1:
            files[0] = self._rename(files[0], preferred_filename)

        results: list[DownloadResult] = []
        for path in files:
            size = path.stat().st_size
            if size > self.max_file_size:
                raise SocialDownloadError(
                    f"O arquivo baixado e muito grande: {human_size(size)}. Limite: {human_size(self.max_file_size)}."
                )
            results.append(
                DownloadResult(
                    path=path,
                    filename=path.name,
                    size=size,
                    mime_type=mimetypes.guess_type(path.name)[0],
                )
            )
        return results

    async def _coalesce_media_files(self, files: list[Path], target_dir: Path, mode: UploadMode) -> list[Path]:
        if mode == "audio":
            return files

        video_files = [path for path in files if _is_video(path)]
        audio_files = [path for path in files if _is_audio(path)]
        ready_video = await _best_ready_video(video_files)
        passthrough = [path for path in files if not _is_video(path) and not _is_audio(path)]
        if ready_video and not audio_files:
            return sorted([*passthrough, ready_video], key=lambda path: path.stat().st_mtime)
        if not video_files or not audio_files:
            return files

        if not self.ffmpeg:
            chosen = ready_video or max(video_files, key=lambda path: path.stat().st_size)
            return sorted([*passthrough, chosen], key=lambda path: path.stat().st_mtime)

        video = max(video_files, key=lambda path: path.stat().st_size)
        audio = max(audio_files, key=lambda path: path.stat().st_size)
        merged = unique_path(target_dir, f"{video.stem}.mp4")
        ok = await _merge_video_audio(self.ffmpeg, video, audio, merged)
        if not ok:
            chosen = ready_video or max(video_files, key=lambda path: path.stat().st_size)
            return sorted([*passthrough, chosen], key=lambda path: path.stat().st_mtime)

        return sorted([*passthrough, merged], key=lambda path: path.stat().st_mtime)

    def _rename(self, path: Path, preferred_filename: str) -> Path:
        sanitized = sanitize_filename(preferred_filename)
        if not sanitized:
            return path

        new_path = unique_path(path.parent, sanitized)
        path.replace(new_path)
        return new_path

    def _read_caption(self, target_dir: Path) -> str | None:
        info_files = sorted(target_dir.rglob("*.info.json"), key=lambda path: path.stat().st_mtime)
        for info_file in info_files:
            try:
                data = json.loads(info_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue

            description = str(data.get("description") or "").strip()
            title = str(data.get("title") or "").strip()
            caption = description or title
            if caption:
                return self._trim_caption(caption)
        return None

    def _trim_caption(self, caption: str) -> str:
        caption = "\n".join(line.rstrip() for line in caption.replace("\r\n", "\n").replace("\r", "\n").splitlines()).strip()
        if len(caption) <= 1000:
            return caption
        return f"{caption[:997].rstrip()}..."


def _clean_progress(line: str) -> str | None:
    text = line.replace("[download]", "").strip()
    if "Destination:" in text or "Merging formats" in text or "Deleting original file" in text:
        return None
    match = re.search(r"(?P<pct>\d+(?:\.\d+)?)%", text)
    if not match:
        return None

    percent = float(match.group("pct"))
    ratio = min(max(percent / 100, 0), 1)
    filled = int(round(ratio * 10))
    bar = "▪" * filled + "▫" * (10 - filled)
    details: list[str] = []
    total_match = re.search(r"of\s+([0-9.]+\s*[KMGTPE]?i?B)", text)
    if total_match:
        total_raw = total_match.group(1).replace(" ", "")
        total_bytes = _size_to_bytes(total_raw)
        current_bytes = int(total_bytes * ratio) if total_bytes is not None else None
        if current_bytes is not None:
            details.append(f"{human_size(current_bytes)} / {human_size(total_bytes)}")
        else:
            details.append(total_raw)
    speed_match = re.search(r"at\s+([^\s]+/s)", text)
    if speed_match:
        details.append(speed_match.group(1).replace(" ", ""))
    eta_match = re.search(r"ETA\s+([0-9:]+)", text)
    if eta_match:
        details.append(f"ETA {eta_match.group(1)}")
    detail_text = f"\n{' • '.join(details)}" if details else ""
    return f"{percent:.2f}%\n[{bar}]{detail_text}"


def _clean_external_progress(line: str) -> str | None:
    match = re.search(
        r"(?P<current>[0-9.]+\s*[KMGT]?i?B)/(?P<total>[0-9.]+\s*[KMGT]?i?B)\((?P<pct>\d+)%\)",
        line,
        re.IGNORECASE,
    )
    if not match:
        return None
    percent = float(match.group("pct"))
    ratio = min(max(percent / 100, 0), 1)
    filled = int(round(ratio * 10))
    bar = "▪" * filled + "▫" * (10 - filled)
    details = [f"{match.group('current').replace(' ', '')} / {match.group('total').replace(' ', '')}"]
    speed_match = re.search(r"(?:DL|SPD):(?P<speed>[0-9.]+\s*[KMGT]?i?B)", line, re.IGNORECASE)
    if speed_match:
        details.append(f"{speed_match.group('speed').replace(' ', '')}/s")
    eta_match = re.search(r"ETA:(?P<eta>[^\]\s]+)", line, re.IGNORECASE)
    if eta_match:
        details.append(f"ETA {eta_match.group('eta')}")
    return f"{percent:.2f}%\n[{bar}]\n{' • '.join(details)}"


def _friendly_error(output: str) -> str:
    output = output.strip().splitlines()[-1:] or [""]
    text = output[0].replace("ERROR:", "").strip()
    if not text:
        return "A plataforma recusou a analise desse link."
    return text[:240]


def _typed_social_error(url: str, output: str) -> BaixaAquiError:
    text = output.lower()
    platform = _platform_from_url(url)
    if _is_auth_error(output):
        if platform == "instagram":
            return CookieRequiredError("[instagram-auth-required]")
        if platform == "facebook":
            return CookieRequiredError("[facebook-auth-required]")
        if platform in {"youtube", "youtube_music"}:
            return CookieRequiredError("[youtube-auth-required]")
        return CookieRequiredError("[auth-required]")
    if any(marker in text for marker in ("http error 429", "too many requests", "captcha", "not a bot", "forbidden", "http error 403")):
        return PlatformBlockedError(_friendly_error(output))
    return SocialDownloadError(_friendly_error(output))


def _is_auth_error(output: str) -> bool:
    text = output.lower()
    return any(
        marker in text
        for marker in (
            "sign in to confirm",
            "cookies needed",
            "authenticated cookies needed",
            "login required",
            "requires authentication",
            "redirect to login page",
            "accounts/login",
            "private video",
        )
    )


def _friendly_gallery_error(url: str, text: str) -> str:
    lowered = text.lower()
    platform = _platform_from_url(url)
    if (
        "authrequired" in lowered
        or "cookies needed" in lowered
        or "authenticated cookies needed" in lowered
        or "401 unauthorized" in lowered
        or "redirect to login page" in lowered
        or "accounts/login" in lowered
    ):
        if platform == "instagram":
            return "[instagram-auth-required]"
        if platform == "facebook":
            return "[facebook-auth-required]"
        if platform == "youtube":
            return "[youtube-auth-required]"
    line = text.strip().splitlines()[-1:] or [""]
    return line[0][:240] if line[0] else "A plataforma recusou a analise desse link."


def _clean_text(value: object, limit: int = 180) -> str | None:
    if not value:
        return None
    text = str(value).replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1].rstrip()}…"


def _float_or_none(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _find_ffmpeg() -> str | None:
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg
    try:
        import imageio_ffmpeg
    except Exception:
        return None
    try:
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def _find_ffprobe(ffmpeg: str | None) -> str | None:
    system_ffprobe = shutil.which("ffprobe")
    if system_ffprobe:
        return system_ffprobe
    if not ffmpeg:
        return None
    candidate = Path(ffmpeg).with_name("ffprobe")
    if candidate.exists():
        return str(candidate)
    candidate_exe = Path(ffmpeg).with_name("ffprobe.exe")
    if candidate_exe.exists():
        return str(candidate_exe)
    return None


def _progressive_only_selector(selector: str) -> str:
    options = [item.strip() for item in selector.split("/") if item.strip()]
    progressive = [
        item
        for item in options
        if "+" not in item and "bestvideo" not in item and "bestaudio" not in item and "mergeall" not in item
    ]
    return "/".join(progressive) or "best[ext=mp4][acodec!=none][vcodec!=none]/best[ext=mp4]/best"


def _is_video(path: Path) -> bool:
    mime = mimetypes.guess_type(path.name)[0] or ""
    return mime.startswith("video/") or path.suffix.lower() in {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v"}


def _is_audio(path: Path) -> bool:
    mime = mimetypes.guess_type(path.name)[0] or ""
    return mime.startswith("audio/") or path.suffix.lower() in {".m4a", ".mp3", ".aac", ".opus", ".ogg", ".wav", ".flac"}


async def _best_ready_video(files: list[Path]) -> Path | None:
    if not files:
        return None
    probe = MediaProbe()
    candidates: list[tuple[int, int, Path]] = []
    for path in files:
        info = await probe.inspect(path)
        if not (info.has_video and info.has_audio):
            continue
        score = (info.width or 0) * (info.height or 0)
        candidates.append((score, path.stat().st_size, path))
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item[0], item[1]))[2]


def _size_to_bytes(value: str) -> int | None:
    match = re.fullmatch(r"(?P<num>\d+(?:\.\d+)?)(?P<unit>[KMGTPE]?i?B)", value)
    if not match:
        return None
    number = float(match.group("num"))
    unit = match.group("unit").upper()
    factors = {
        "B": 1,
        "KB": 1000,
        "MB": 1000**2,
        "GB": 1000**3,
        "TB": 1000**4,
        "KIB": 1024,
        "MIB": 1024**2,
        "GIB": 1024**3,
        "TIB": 1024**4,
    }
    factor = factors.get(unit)
    if not factor:
        return None
    return int(number * factor)


async def _merge_video_audio(ffmpeg: str, video: Path, audio: Path, target: Path) -> bool:
    cmd = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(video),
        "-i",
        str(audio),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-shortest",
        "-movflags",
        "+faststart",
        str(target),
    ]
    try:
        completed = await asyncio.to_thread(
            subprocess.run,
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except Exception:
        return False
    return completed.returncode == 0 and target.exists() and target.stat().st_size > 0


def _best_quality(formats: list[dict[str, object]]) -> str | None:
    heights: list[int] = []
    for item in formats:
        try:
            height = int(item.get("height") or 0)
        except (TypeError, ValueError):
            height = 0
        if height:
            heights.append(height)
    if heights:
        return f"ate {max(heights)}p"
    return None


def _quality_list(formats: list[dict[str, object]]) -> list[int]:
    qualities: set[int] = set()
    for item in formats:
        try:
            height = int(item.get("height") or 0)
        except (TypeError, ValueError):
            height = 0
        if height >= 144:
            qualities.add(height)
    return sorted(qualities, reverse=True)[:8]


def _media_type(data: dict[str, object], item_count: int) -> str:
    if item_count > 1:
        return "album"
    ext = str(data.get("ext") or "").lower()
    if ext in {"jpg", "jpeg", "png", "webp", "gif"}:
        return "image"
    raw_type = str(data.get("_type") or data.get("type") or "").lower()
    if raw_type in {"photo", "image"}:
        return "image"
    if data.get("duration"):
        return "video"
    return "media"


def _should_try_gallery_dl(url: str, output: str) -> bool:
    lowered = output.lower()
    platform = _platform_from_url(url)
    path = urlparse(url).path.lower()
    if platform == "tiktok" and "/photo/" in path:
        return True
    if platform == "x" and "no video could be found" in lowered:
        return True
    if platform in {"instagram", "facebook"} and (
        "cannot parse data" in lowered
        or "unsupported url" in lowered
        or "story" in path
        or "/p/" in path
        or "/stories/" in path
    ):
        return True
    return platform in {"x", "tiktok"} and "unsupported url" in lowered


def _should_refine_with_gallery(url: str, payload: dict[str, object], info: SocialInfo) -> bool:
    platform = _platform_from_url(url)
    if platform not in {"instagram", "facebook", "x", "tiktok"}:
        return False
    if info.provider != "yt_dlp":
        return False
    if info.media_type != "media":
        return False
    if int(payload.get("playlist_count") or 0) == 0 and str(payload.get("_type") or "").lower() == "playlist":
        return True
    path = urlparse(url).path.lower()
    return path.startswith("/stories/") or "/p/" in path or "/photo/" in path


def _platform_from_url(url: str) -> str:
    hostname = (urlparse(url).hostname or "").lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    if hostname == "music.youtube.com":
        return "youtube_music"
    if hostname in {"twitter.com", "x.com"}:
        return "x"
    if "tiktok" in hostname:
        return "tiktok"
    if "instagram" in hostname:
        return "instagram"
    if "facebook" in hostname or hostname == "fb.watch":
        return "facebook"
    if "youtu" in hostname:
        return "youtube"
    if "spotify" in hostname:
        return "spotify"
    if "twitch" in hostname:
        return "twitch"
    if "reddit" in hostname or hostname == "redd.it":
        return "reddit"
    if "pinterest" in hostname or hostname == "pin.it":
        return "pinterest"
    if "soundcloud" in hostname:
        return "soundcloud"
    if "kwai" in hostname or hostname == "kw.ai":
        return "kwai"
    return hostname or "unknown"


def _parse_gallery_payload(
    url: str,
    payload: list[object],
) -> tuple[dict[str, object], list[SocialMediaItem], set[str]]:
    metadata: dict[str, object] = {}
    media_items: list[SocialMediaItem] = []
    gallery_types: set[str] = set()
    for row in payload:
        if not isinstance(row, list) or not row:
            continue
        row_kind = row[0]
        if row_kind == -1 and len(row) > 1 and isinstance(row[1], dict):
            details = row[1]
            message = str(details.get("message") or details.get("error") or "").strip()
            raise SocialDownloadError(_friendly_gallery_error(url, message))
        if row_kind == 2 and len(row) > 1 and isinstance(row[1], dict):
            metadata = row[1]
            continue
        if row_kind != 3 or len(row) < 3 or not isinstance(row[1], str) or not isinstance(row[2], dict):
            continue
        item_url = row[1]
        item_data = row[2]
        item_kind = _gallery_item_kind(item_data, item_url)
        gallery_types.add(item_kind)
        filename = _gallery_item_filename(item_data, item_url)
        mime_type = mimetypes.guess_type(filename)[0]
        media_items.append(SocialMediaItem(url=item_url, filename=filename, mime_type=mime_type, kind=item_kind))
    if not media_items:
        raise SocialDownloadError("Nao encontrei arquivos de midia nesse link.")
    return metadata, media_items, gallery_types


def _gallery_item_kind(data: dict[str, object], url: str) -> str:
    raw = str(data.get("type") or "").lower()
    if raw in {"photo", "image"}:
        return "image"
    if raw == "video":
        return "video"
    if raw == "audio":
        return "audio"
    extension = str(data.get("extension") or "").lower()
    if extension in {"jpg", "jpeg", "png", "webp", "gif"}:
        return "image"
    if extension in {"mp4", "mkv", "mov", "webm"}:
        return "video"
    if extension in {"m4a", "mp3", "aac", "ogg", "opus", "wav", "flac"}:
        return "audio"
    mime_type = mimetypes.guess_type(url)[0] or ""
    if mime_type.startswith("image/"):
        return "image"
    if mime_type.startswith("video/"):
        return "video"
    if mime_type.startswith("audio/"):
        return "audio"
    return "file"


def _gallery_item_filename(data: dict[str, object], url: str) -> str:
    raw_name = sanitize_filename(str(data.get("filename") or "")) or Path(urlparse(url).path).name or "media"
    extension = str(data.get("extension") or "").strip().lstrip(".")
    if not extension:
        extension = parse_qs(urlparse(url).query).get("format", [""])[0].strip().lstrip(".")
    if extension and not Path(raw_name).suffix:
        raw_name = f"{raw_name}.{extension}"
    return sanitize_filename(raw_name) or "media.bin"


def _gallery_author(metadata: dict[str, object]) -> str | None:
    author = metadata.get("author")
    if isinstance(author, dict):
        return str(author.get("nick") or author.get("name") or author.get("nickname") or "").strip() or None
    user = metadata.get("user")
    if isinstance(user, dict):
        return str(user.get("nick") or user.get("name") or "").strip() or None
    if isinstance(user, str):
        return user.strip() or None
    return str(metadata.get("authorName") or "").strip() or None


def _gallery_thumbnail(metadata: dict[str, object]) -> str | None:
    for key in ("thumbnail", "cover", "profile_image"):
        value = metadata.get(key)
        if isinstance(value, str) and value.startswith(("https://", "http://")):
            return value
    return None


def _gallery_media_type(items: list[SocialMediaItem], gallery_types: set[str]) -> str:
    image_count = sum(1 for item in items if item.kind == "image")
    video_count = sum(1 for item in items if item.kind == "video")
    audio_count = sum(1 for item in items if item.kind == "audio")
    if image_count + video_count > 1:
        return "album"
    if image_count:
        return "image"
    if video_count:
        return "video"
    if audio_count or "audio" in gallery_types:
        return "audio"
    return "media"


def _select_gallery_items(info: SocialInfo, mode: UploadMode) -> list[SocialMediaItem]:
    images = [item for item in info.media_items if item.kind == "image"]
    videos = [item for item in info.media_items if item.kind == "video"]
    audios = [item for item in info.media_items if item.kind == "audio"]
    other = [item for item in info.media_items if item.kind not in {"image", "video", "audio"}]

    if mode == "audio":
        return audios or videos
    if mode == "photo":
        return images
    if mode == "video":
        return videos
    if images and not videos:
        return images
    if videos:
        return videos + images
    if audios:
        return audios
    return other


def _new_media_files(target_dir: Path, before: set[Path]) -> list[Path]:
    files = [
        path
        for path in target_dir.rglob("*")
        if path.is_file()
        and path.resolve() not in before
        and not path.name.endswith(".part")
        and not path.name.endswith(".info.json")
        and not path.name.endswith(".json")
        and not path.name.endswith(".txt")
    ]
    files.sort(key=lambda path: (path.parent.as_posix(), path.name.lower()))
    return files


def _gallery_progress_text(index: int, total_items: int, current: int, total: int | None) -> str:
    if total and total > 0:
        ratio = min(max(current / total, 0), 1)
        filled = int(round(ratio * 10))
        bar = "#" * filled + "-" * (10 - filled)
        return f"{index}/{total_items} • {ratio * 100:.2f}%\n[{bar}]\n{human_size(current)} / {human_size(total)}"
    return f"{index}/{total_items}\n{human_size(current)}"


def _gallery_kind_from_path(path: Path) -> str:
    if _is_video(path):
        return "video"
    if _is_audio(path):
        return "audio"
    mime = mimetypes.guess_type(path.name)[0] or ""
    if mime.startswith("image/") or path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return "image"
    return "file"


def _filter_gallery_files(files: list[Path], desired_kinds: set[str]) -> list[Path]:
    if not desired_kinds:
        return files
    filtered = [path for path in files if _gallery_kind_from_path(path) in desired_kinds]
    return filtered or files


def _gallery_download_text(done: int, total_items: int, filename: str) -> str:
    ratio = min(max(done / max(total_items, 1), 0), 1)
    filled = int(round(ratio * 10))
    bar = "▪" * filled + "▫" * (10 - filled)
    clean_name = sanitize_filename(Path(filename).name) or Path(filename).name or "arquivo"
    return f"{done}/{total_items} • {ratio * 100:.2f}%\n[{bar}]\n{clean_name[:56]}"
