from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MediaInfo:
    width: int | None = None
    height: int | None = None
    duration: float | None = None
    codec: str | None = None
    has_video: bool = False
    has_audio: bool = False
    rotation: int = 0

    @property
    def aspect_label(self) -> str:
        if not self.width or not self.height:
            return "desconhecido"
        if abs(self.width - self.height) <= 8:
            return "quadrado"
        return "vertical" if self.height > self.width else "horizontal"


class MediaProbe:
    def __init__(self) -> None:
        self.ffprobe = shutil.which("ffprobe")
        self.ffmpeg = _find_ffmpeg()

    async def inspect(self, path: Path) -> MediaInfo:
        if self.ffprobe:
            info = await self._inspect_ffprobe(path)
            if info.has_video or info.has_audio:
                return info
        if self.ffmpeg:
            info = await self._inspect_ffmpeg(path)
            if info.has_video or info.has_audio:
                return info
        return await asyncio.to_thread(_inspect_hachoir, path)

    async def _inspect_ffprobe(self, path: Path) -> MediaInfo:
        cmd = [
            self.ffprobe or "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=20)
            data = json.loads(stdout.decode("utf-8", errors="replace") or "{}")
        except Exception:
            return MediaInfo()
        return _info_from_streams(data)

    async def _inspect_ffmpeg(self, path: Path) -> MediaInfo:
        cmd = [
            self.ffmpeg or "ffmpeg",
            "-hide_banner",
            "-i",
            str(path),
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=20)
        except Exception:
            return MediaInfo()

        text = stderr.decode("utf-8", errors="replace")
        width = height = None
        duration = None
        codec = None
        has_video = " Video: " in text
        has_audio = " Audio: " in text
        rotation = 0

        duration_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
        if duration_match:
            hours = int(duration_match.group(1))
            minutes = int(duration_match.group(2))
            seconds = float(duration_match.group(3))
            duration = hours * 3600 + minutes * 60 + seconds

        video_match = re.search(r"Video:\s*([^,]+),.*?(\d{2,5})x(\d{2,5})", text, flags=re.DOTALL)
        if video_match:
            codec = video_match.group(1).strip()
            width = int(video_match.group(2))
            height = int(video_match.group(3))

        rotation_match = re.search(r"rotate\s*:\s*(-?\d+)", text)
        if rotation_match:
            rotation = int(rotation_match.group(1)) % 360
        else:
            displaymatrix_match = re.search(r"rotation of (-?\d+(?:\.\d+)?) degrees", text)
            if displaymatrix_match:
                rotation = int(float(displaymatrix_match.group(1))) % 360

        if rotation in {90, 270} and width and height:
            width, height = height, width

        return MediaInfo(
            width=width,
            height=height,
            duration=duration,
            codec=codec,
            has_video=has_video,
            has_audio=has_audio,
            rotation=rotation,
        )

    async def thumbnail(self, path: Path, target: Path) -> Path | None:
        if not self.ffmpeg:
            return None
        for seek in ("00:00:00.2", "00:00:00"):
            cmd = [
                self.ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                seek,
                "-i",
                str(path),
                "-frames:v",
                "1",
                "-vf",
                "scale=if(gt(a\\,1)\\,320\\,-2):if(gt(a\\,1)\\,-2\\,320)",
                "-q:v",
                "3",
                str(target),
            ]
            try:
                await asyncio.to_thread(subprocess.run, cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                continue
            if target.exists() and target.stat().st_size > 0:
                return target
        return None


def _info_from_streams(data: dict[str, object]) -> MediaInfo:
    width = height = None
    duration = None
    codec = None
    has_video = has_audio = False
    rotation = 0
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video" and not has_video:
            has_video = True
            width = int(stream.get("width") or 0) or None
            height = int(stream.get("height") or 0) or None
            codec = stream.get("codec_name")
            duration = _float_or_none(stream.get("duration"))
            rotation = _rotation_from_stream(stream)
        elif stream.get("codec_type") == "audio":
            has_audio = True
    if duration is None:
        duration = _float_or_none(data.get("format", {}).get("duration"))
    if rotation in {90, 270} and width and height:
        width, height = height, width
    return MediaInfo(width=width, height=height, duration=duration, codec=codec, has_video=has_video, has_audio=has_audio, rotation=rotation)


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


def _inspect_hachoir(path: Path) -> MediaInfo:
    try:
        from hachoir.metadata import extractMetadata
        from hachoir.parser import createParser
    except Exception:
        return MediaInfo()

    parser = None
    try:
        parser = createParser(str(path))
        if not parser:
            return MediaInfo()
        metadata = extractMetadata(parser)
        if not metadata:
            return MediaInfo()

        width = _int_or_none(_metadata_value(metadata, "width"))
        height = _int_or_none(_metadata_value(metadata, "height"))
        duration = _duration_seconds(_metadata_value(metadata, "duration"))
        has_video = bool(width and height)
        return MediaInfo(width=width, height=height, duration=duration, has_video=has_video)
    except Exception:
        return MediaInfo()
    finally:
        if parser is not None:
            try:
                parser.stream.close()
            except Exception:
                pass


def _metadata_value(metadata, key: str):
    try:
        return metadata.get(key)
    except Exception:
        return None


def _duration_seconds(value: object) -> float | None:
    if value is None:
        return None
    if hasattr(value, "total_seconds"):
        return float(value.total_seconds())
    return _float_or_none(value)


def _rotation_from_stream(stream: dict[str, object]) -> int:
    tags = stream.get("tags")
    if isinstance(tags, dict):
        rotation = _int_or_none(tags.get("rotate"))
        if rotation is not None:
            return rotation % 360
    side_data = stream.get("side_data_list")
    if isinstance(side_data, list):
        for item in side_data:
            if isinstance(item, dict):
                rotation = _int_or_none(item.get("rotation"))
                if rotation is not None:
                    return rotation % 360
    return 0


def _int_or_none(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _float_or_none(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
