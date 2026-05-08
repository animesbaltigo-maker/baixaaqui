from __future__ import annotations

import asyncio
import random
from pathlib import Path
from typing import Callable

from telethon.tl.functions.upload import SaveBigFilePartRequest
from telethon.tl.types import InputFileBig


ProgressCallback = Callable[[int, int], None]


def should_parallel_upload(path: Path, enabled: bool, threshold: int) -> bool:
    return enabled and path.stat().st_size >= threshold


async def upload_big_file_parallel(
    client,
    path: Path,
    filename: str,
    workers: int,
    progress: ProgressCallback,
):
    file_size = path.stat().st_size
    part_size = 512 * 1024
    total_parts = (file_size + part_size - 1) // part_size
    file_id = random.randrange(-(2**63), 2**63)

    next_part = 0
    completed = 0
    part_lock = asyncio.Lock()
    progress_lock = asyncio.Lock()

    async def reserve_part() -> int | None:
        nonlocal next_part
        async with part_lock:
            if next_part >= total_parts:
                return None
            part = next_part
            next_part += 1
            return part

    async def worker() -> None:
        nonlocal completed
        with path.open("rb") as file:
            while True:
                part = await reserve_part()
                if part is None:
                    return

                chunk = await asyncio.to_thread(_read_part_from_handle, file, part, part_size)
                await client(SaveBigFilePartRequest(file_id, part, total_parts, chunk))
                async with progress_lock:
                    completed += len(chunk)
                    progress(completed, file_size)

    await asyncio.gather(*(worker() for _ in range(max(workers, 1))))
    return InputFileBig(file_id, total_parts, filename)


def upload_workers_for_size(size: int, configured_workers: int) -> int:
    mb = size / 1024 / 1024
    if mb < 100:
        recommended = 2
    elif mb < 700:
        recommended = 4
    elif mb < 1900:
        recommended = 6
    else:
        recommended = 8
    return max(1, min(configured_workers, recommended))


def _read_part_from_handle(file, part: int, part_size: int) -> bytes:
    file.seek(part * part_size)
    return file.read(part_size)
