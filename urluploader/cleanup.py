from __future__ import annotations

import shutil
import time
from pathlib import Path


def directory_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                continue
    return total


def cleanup_old_dirs(root: Path, ttl_hours: int) -> int:
    if not root.exists():
        return 0
    cutoff = time.time() - ttl_hours * 3600
    removed = 0
    for item in root.iterdir():
        try:
            if item.stat().st_mtime > cutoff:
                continue
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            elif item.is_file():
                item.unlink(missing_ok=True)
            removed += 1
        except OSError:
            continue
    return removed


def cleanup_dir_contents(root: Path) -> int:
    if not root.exists():
        return 0
    removed = 0
    for item in root.iterdir():
        try:
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            else:
                item.unlink(missing_ok=True)
            removed += 1
        except OSError:
            continue
    return removed
