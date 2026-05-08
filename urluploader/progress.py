from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable
from typing import TypeAlias

from telethon.errors import FloodWaitError, MessageNotModifiedError


def human_size(size: int | float | None) -> str:
    if size is None:
        return "desconhecido"

    amount = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1024 or unit == "TB":
            return f"{amount:.1f} {unit}" if unit != "B" else f"{int(amount)} B"
        amount /= 1024
    return f"{amount:.1f} TB"


def render_progress(
    label: str,
    current: int,
    total: int | None,
    started_at: float,
    *,
    current_speed: float | None = None,
) -> str:
    elapsed = max(time.monotonic() - started_at, 0.001)
    average_speed = current / elapsed
    display_speed = current_speed if current_speed and current_speed > 0 else average_speed
    elapsed_text = _format_duration(int(elapsed))

    if total:
        ratio = min(max(current / total, 0), 1)
        percent = ratio * 100
        filled = int(round(ratio * 12))
        bar = "#" * filled + "-" * (12 - filled)
        eta = int((total - current) / display_speed) if display_speed > 0 and current < total else 0
        eta_text = _format_duration(eta) if eta else "finalizando"
        return (
            f"<b>{label}</b>: {percent:.2f}%\n"
            f"<code>[{bar}]</code>\n"
            f"Baixado: <code>{human_size(current)} / {human_size(total)}</code>\n"
            f"Velocidade: <code>{_format_speed(display_speed)}</code>\n"
            f"Media: <code>{_format_speed(average_speed)}</code>\n"
            f"ETA: <code>{eta_text}</code>"
        )

    if current <= 0:
        return (
            f"<b>{label}</b>\n"
            f"<code>[--- conectando ---]</code>\n"
            f"Status: <code>preparando download</code>\n"
            f"Baixado: <code>aguardando primeiros bytes</code>\n"
            f"Tempo: <code>{elapsed_text}</code>"
        )

    bar = _indeterminate_bar(elapsed)
    return (
        f"<b>{label}</b>\n"
        f"<code>[{bar}]</code>\n"
        f"Status: <code>baixando, tamanho nao informado</code>\n"
        f"Baixado: <code>{human_size(current)}</code>\n"
        f"Velocidade: <code>{_format_speed(display_speed)}</code>\n"
        f"Media: <code>{_format_speed(average_speed)}</code>\n"
        f"Tempo: <code>{elapsed_text}</code>"
    )


def _format_speed(speed: float) -> str:
    if speed <= 1:
        return "calculando..."
    return f"{human_size(speed)}/s"


def _format_duration(seconds: int) -> str:
    seconds = max(seconds, 0)
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}h {minutes:02d}m {sec:02d}s"
    if minutes:
        return f"{minutes:d}m {sec:02d}s"
    return f"{sec:d}s"


def _indeterminate_bar(elapsed: float) -> str:
    width = 12
    block = 3
    start = int(elapsed) % (width - block + 1)
    chars = ["-"] * width
    for index in range(start, start + block):
        chars[index] = "#"
    return "".join(chars)


ProgressWrapper: TypeAlias = Callable[[str], str]


class SpeedMeter:
    def __init__(self, window_seconds: float = 5.0) -> None:
        self.window_seconds = max(window_seconds, 1.0)
        self.samples: deque[tuple[float, int]] = deque()

    def update(self, current: int) -> float:
        now = time.monotonic()
        self.samples.append((now, current))
        while len(self.samples) > 1 and self.samples[0][0] < now - self.window_seconds:
            self.samples.popleft()
        if len(self.samples) < 2:
            return 0.0
        oldest_time, oldest_bytes = self.samples[0]
        newest_time, newest_bytes = self.samples[-1]
        return (newest_bytes - oldest_bytes) / max(newest_time - oldest_time, 0.001)


class ProgressEditor:
    def __init__(
        self,
        message,
        label: str,
        interval: float,
        wrapper: ProgressWrapper | None = None,
        buttons=None,
        percent_step: int = 5,
    ) -> None:
        self.message = message
        self.label = label
        self.interval = max(interval, 0.75)
        self.percent_step = max(1, percent_step)
        self.wrapper = wrapper
        self.buttons = [] if buttons is None else buttons
        self.started_at = time.monotonic()
        self._last_edit = 0.0
        self._last_schedule = 0.0
        self._last_percent = -1
        self._loop = asyncio.get_running_loop()
        self._pending_task: asyncio.Task[None] | None = None
        self._speed_meter = SpeedMeter()

    async def update(self, current: int, total: int | None) -> None:
        if self.message is None:
            return

        now = time.monotonic()
        percent_bucket = int((current / total) * 100) if total and total > 0 else -1
        if total and current >= total:
            should_edit = True
        else:
            should_edit = (
                now - self._last_edit >= self.interval
                or self._last_percent < 0
                or percent_bucket >= self._last_percent + self.percent_step
            )

        if not should_edit:
            return

        self._last_edit = now
        self._last_percent = percent_bucket
        current_speed = self._speed_meter.update(current)
        text = render_progress(self.label, current, total, self.started_at, current_speed=current_speed)
        if self.wrapper:
            text = self.wrapper(text)
        try:
            await self.message.edit(text, parse_mode="html", buttons=self.buttons)
        except (FloodWaitError, MessageNotModifiedError):
            return
        except Exception:
            return

    def as_callback(self) -> Callable[[int, int], None]:
        def callback(current: int, total: int) -> None:
            if self.message is None:
                return

            now = time.monotonic()
            percent_bucket = int((current / total) * 100) if total and total > 0 else -1
            if total and current >= total:
                should_schedule = True
            else:
                should_schedule = (
                    now - self._last_schedule >= self.interval
                    or self._last_percent < 0
                    or percent_bucket >= self._last_percent + self.percent_step
                )

            if should_schedule:
                self._last_schedule = now
                if self._pending_task and not self._pending_task.done():
                    self._pending_task.cancel()
                self._pending_task = self._loop.create_task(self.update(current, total))

        return callback


ProgressCallback = Callable[[int, int | None], Awaitable[None]]
