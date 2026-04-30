from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from urluploader.config import load_settings
from urluploader.diagnostics import run_diagnostics


async def main() -> int:
    settings = load_settings()
    results = await run_diagnostics(settings)
    failed = False
    for item in results:
        status = "OK" if item.ok else "FAIL"
        print(f"[{status}] {item.name}: {item.detail}")
        failed = failed or not item.ok
    return 1 if failed and "--strict" in sys.argv else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
