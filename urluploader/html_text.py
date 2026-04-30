from __future__ import annotations

from html import escape


def h(value: object | None) -> str:
    """Escape user/provider text before inserting into HTML parse_mode messages."""
    return escape("" if value is None else str(value), quote=False)


def preserve(value: str | None, max_length: int = 1000) -> str:
    if not value:
        return ""
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    lines = [" ".join(line.split()) if line.strip() else "" for line in text.split("\n")]
    cleaned = "\n".join(lines).strip()
    if len(cleaned) <= max_length:
        return cleaned
    return f"{cleaned[: max_length - 1].rstrip()}…"


def mono(value: object | None) -> str:
    return f"<code>{h(value)}</code>"
