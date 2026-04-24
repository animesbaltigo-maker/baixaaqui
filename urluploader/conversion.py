from __future__ import annotations

import asyncio
import mimetypes
import shutil
import subprocess
import uuid
import zipfile
from html import escape
from io import BytesIO
from pathlib import Path

from .media_probe import MediaProbe
from .models import DownloadResult
from .names import sanitize_filename, unique_path


class ConversionError(Exception):
    """Raised when a media/document conversion cannot be completed safely."""


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
EPUB_IMAGE_EXTENSIONS = IMAGE_EXTENSIONS | {".gif"}


async def convert_document(result: DownloadResult, target_format: str, work_dir: Path) -> DownloadResult:
    target_format = target_format.lower().lstrip(".")
    source_suffix = result.path.suffix.lower().lstrip(".")
    if target_format not in {"pdf", "cbz", "epub"}:
        raise ConversionError("Formato de conversão inválido.")
    if source_suffix == target_format:
        return result

    if source_suffix == "cbz" and target_format == "pdf":
        path = await asyncio.to_thread(_cbz_to_pdf, result.path, work_dir)
    elif source_suffix == "cbz" and target_format == "epub":
        path = await asyncio.to_thread(_cbz_to_epub, result.path, work_dir)
    elif source_suffix == "pdf" and target_format == "cbz":
        path = await asyncio.to_thread(_pdf_to_cbz, result.path, work_dir)
    elif source_suffix == "pdf" and target_format == "epub":
        cbz = await asyncio.to_thread(_pdf_to_cbz, result.path, work_dir)
        path = await asyncio.to_thread(_cbz_to_epub, cbz, work_dir)
    elif source_suffix == "epub" and target_format == "cbz":
        path = await asyncio.to_thread(_epub_to_cbz, result.path, work_dir)
    elif source_suffix == "epub" and target_format == "pdf":
        cbz = await asyncio.to_thread(_epub_to_cbz, result.path, work_dir)
        path = await asyncio.to_thread(_cbz_to_pdf, cbz, work_dir)
    else:
        raise ConversionError("Esse tipo de arquivo não possui uma conversão compatível aqui.")

    return DownloadResult(
        path=path,
        filename=path.name,
        size=path.stat().st_size,
        mime_type=mimetypes.guess_type(path.name)[0],
        caption=result.caption,
    )


async def ensure_mp4_video(result: DownloadResult, work_dir: Path, ffmpeg: str | None, *, normalize: bool = True) -> DownloadResult:
    probe = MediaProbe()
    source_info = await probe.inspect(result.path)
    codec = (source_info.codec or "").lower()
    codec_is_mobile_safe = codec in {"h264", "avc1"}
    if result.path.suffix.lower() == ".mp4" and source_info.rotation == 0 and source_info.has_audio and codec_is_mobile_safe:
        return result
    if not ffmpeg:
        if result.path.suffix.lower() == ".mp4":
            return result
        raise ConversionError("O FFmpeg não está instalado para converter este vídeo em MP4.")

    output_dir = work_dir / "normalized_video"
    output_dir.mkdir(parents=True, exist_ok=True)
    target = unique_path(output_dir, f"{result.path.stem}.mp4")
    copy_cmd = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(result.path),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        str(target),
    ]
    copied_ok = False
    if result.path.suffix.lower() == ".mp4" and source_info.rotation == 0 and codec_is_mobile_safe:
        copied_ok = await _run_ffmpeg(copy_cmd) and target.exists() and target.stat().st_size > 0
        if copied_ok:
            copied_info = await probe.inspect(target)
            copied_ok = bool(copied_info.has_video and copied_info.has_audio and (copied_info.codec or "").lower() in {"h264", "avc1"})
    if not copied_ok:
        target.unlink(missing_ok=True)
        video_filters: list[str] = []
        if source_info.rotation == 90:
            video_filters.append("transpose=clock")
        elif source_info.rotation == 270:
            video_filters.append("transpose=cclock")
        elif source_info.rotation == 180:
            video_filters.extend(["transpose=clock", "transpose=clock"])
        video_filters.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")
        encode_cmd = [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(result.path),
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            "-vf",
            ",".join(video_filters),
            "-pix_fmt",
            "yuv420p",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-map_metadata",
            "-1",
            "-metadata:s:v:0",
            "rotate=0",
            "-movflags",
            "+faststart",
            str(target),
        ]
        if not await _run_ffmpeg(encode_cmd) or not target.exists() or target.stat().st_size == 0:
            raise ConversionError("Não consegui converter este vídeo para MP4 com segurança.")

    return DownloadResult(target, target.name, target.stat().st_size, "video/mp4", result.caption)


async def _run_ffmpeg(cmd: list[str]) -> bool:
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
    return completed.returncode == 0


def _pil_image_module():
    try:
        from PIL import Image
    except ImportError as exc:
        raise ConversionError("A biblioteca Pillow é necessária para esta conversão.") from exc
    return Image


def _fitz_module():
    try:
        import fitz
    except ImportError as exc:
        raise ConversionError("A biblioteca PyMuPDF é necessária para converter PDF.") from exc
    return fitz


def _safe_stem(path: Path) -> str:
    return sanitize_filename(path.stem) or f"arquivo-{uuid.uuid4().hex[:8]}"


def _image_entries_from_zip(path: Path, extensions: set[str]) -> list[tuple[str, bytes]]:
    entries: list[tuple[str, bytes]] = []
    with zipfile.ZipFile(path) as archive:
        names = [
            name
            for name in archive.namelist()
            if not name.endswith("/") and Path(name).suffix.lower() in extensions and "__MACOSX" not in name
        ]
        for name in sorted(names, key=_natural_sort_key):
            entries.append((Path(name).name, archive.read(name)))
    if not entries:
        raise ConversionError("Não encontrei imagens válidas dentro desse arquivo.")
    return entries


def _natural_sort_key(value: str) -> list[object]:
    import re

    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", value)]


def _cbz_to_pdf(path: Path, work_dir: Path) -> Path:
    Image = _pil_image_module()
    images = []
    for _, data in _image_entries_from_zip(path, EPUB_IMAGE_EXTENSIONS):
        image = Image.open(BytesIO(data))
        if image.mode in {"RGBA", "LA", "P"}:
            image = image.convert("RGB")
        images.append(image.copy())

    output = unique_path(work_dir, f"{_safe_stem(path)}.pdf")
    first, rest = images[0], images[1:]
    first.save(output, "PDF", save_all=True, append_images=rest)
    return output


def _cbz_to_epub(path: Path, work_dir: Path) -> Path:
    entries = _image_entries_from_zip(path, EPUB_IMAGE_EXTENSIONS)
    output = unique_path(work_dir, f"{_safe_stem(path)}.epub")
    title = escape(_safe_stem(path))
    with zipfile.ZipFile(output, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        epub.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>""",
        )

        manifest_items = []
        spine_items = []
        for index, (name, data) in enumerate(entries, start=1):
            ext = Path(name).suffix.lower() or ".jpg"
            image_name = f"images/page-{index:04d}{ext}"
            page_name = f"pages/page-{index:04d}.xhtml"
            media_type = mimetypes.guess_type(image_name)[0] or "image/jpeg"
            epub.writestr(f"OEBPS/{image_name}", data)
            epub.writestr(
                f"OEBPS/{page_name}",
                f"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>Página {index}</title></head>
  <body style="margin:0;padding:0;text-align:center;background:#fff;">
    <img src="../{image_name}" alt="Página {index}" style="max-width:100%;height:auto;"/>
  </body>
</html>""",
            )
            manifest_items.append(f'<item id="img{index}" href="{image_name}" media-type="{media_type}"/>')
            manifest_items.append(f'<item id="page{index}" href="{page_name}" media-type="application/xhtml+xml"/>')
            spine_items.append(f'<itemref idref="page{index}"/>')

        epub.writestr(
            "OEBPS/content.opf",
            f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">urn:uuid:{uuid.uuid4()}</dc:identifier>
    <dc:title>{title}</dc:title>
    <dc:language>pt-BR</dc:language>
  </metadata>
  <manifest>
    {''.join(manifest_items)}
  </manifest>
  <spine>
    {''.join(spine_items)}
  </spine>
</package>""",
        )
    return output


def _pdf_to_cbz(path: Path, work_dir: Path) -> Path:
    fitz = _fitz_module()
    output = unique_path(work_dir, f"{_safe_stem(path)}.cbz")
    document = fitz.open(path)
    try:
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as cbz:
            for index, page in enumerate(document, start=1):
                pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                cbz.writestr(f"page-{index:04d}.jpg", pixmap.tobytes("jpeg", jpg_quality=90))
    finally:
        document.close()
    return output


def _epub_to_cbz(path: Path, work_dir: Path) -> Path:
    output = unique_path(work_dir, f"{_safe_stem(path)}.cbz")
    entries = _image_entries_from_zip(path, EPUB_IMAGE_EXTENSIONS)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as cbz:
        for index, (name, data) in enumerate(entries, start=1):
            suffix = Path(name).suffix.lower() or ".jpg"
            cbz.writestr(f"page-{index:04d}{suffix}", data)
    return output


def cleanup_conversion_cache(work_dir: Path) -> None:
    shutil.rmtree(work_dir, ignore_errors=True)
