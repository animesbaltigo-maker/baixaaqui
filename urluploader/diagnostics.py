from __future__ import annotations

import asyncio
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .cleanup import directory_size
from .cookies import CookieStatus, inspect_all_cookies


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


async def command_version(module_or_binary: str, *args: str, module: bool = False, timeout: int = 12) -> CheckResult:
    cmd = [sys.executable, "-m", module_or_binary, *args] if module else [module_or_binary, *args]
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
        text = stdout.decode("utf-8", errors="replace").strip().splitlines()
        detail = text[0] if text else f"exit {process.returncode}"
        return CheckResult(module_or_binary, process.returncode == 0, detail[:160])
    except FileNotFoundError:
        return CheckResult(module_or_binary, False, "not found")
    except asyncio.TimeoutError:
        return CheckResult(module_or_binary, False, "timeout")
    except Exception as exc:
        return CheckResult(module_or_binary, False, str(exc)[:160])


def path_check(path: Path, name: str) -> CheckResult:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return CheckResult(name, True, str(path))
    except Exception as exc:
        return CheckResult(name, False, f"{path}: {exc}")


def disk_check(path: Path) -> CheckResult:
    try:
        usage = shutil.disk_usage(path)
        free_gb = usage.free / 1024**3
        return CheckResult("disk", free_gb > 1, f"{free_gb:.1f} GB free")
    except Exception as exc:
        return CheckResult("disk", False, str(exc))


def cookie_checks(default_cookie_file: str, platform_files: dict[str, str], max_age_hours: int) -> list[CheckResult]:
    results: list[CheckResult] = []
    for item in inspect_all_cookies(default_cookie_file, platform_files, max_age_hours):
        detail = cookie_detail(item)
        results.append(CheckResult(f"cookies:{item.platform}", item.usable, detail))
    return results


def cookie_detail(item: CookieStatus) -> str:
    if not item.path:
        return item.warning or "not configured"
    age = f", age={item.age_hours:.1f}h" if item.age_hours is not None else ""
    warning = f", warning={item.warning}" if item.warning else ""
    return f"{item.path}, exists={item.exists}, readable={item.readable}, netscape={item.valid_netscape}{age}{warning}"


async def run_diagnostics(settings) -> list[CheckResult]:
    results: list[CheckResult] = [
        CheckResult("python", sys.version_info >= (3, 11), sys.version.split()[0]),
        path_check(settings.data_dir, "data_dir"),
        path_check(settings.download_dir, "download_dir"),
        path_check(settings.public_files_dir, "public_files_dir"),
        disk_check(settings.app_dir),
    ]
    results.extend(cookie_checks(settings.ytdlp_cookies_file, settings.ytdlp_platform_cookies, settings.ytdlp_cookies_max_age_hours))
    results.extend(
        await asyncio.gather(
            command_version("yt_dlp", "--version", module=True),
            command_version("gallery_dl", "--version", module=True),
            command_version("ffmpeg", "-version"),
            command_version("ffprobe", "-version"),
            command_version("aria2c", "--version"),
        )
    )
    return results


def render_diagnostics(results: Iterable[CheckResult]) -> str:
    lines = ["<b>Diagnostico da VPS</b>"]
    for item in results:
        mark = "OK" if item.ok else "ERRO"
        lines.append(f"<code>{mark}</code> <b>{item.name}</b>: {item.detail}")
    return "\n".join(lines)
