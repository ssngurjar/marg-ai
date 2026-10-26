"""Shared helpers for the S2 measurement spikes (s02 §5)."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Awaitable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Timing:
    label: str
    seconds: float


async def timed[T](label: str, call: Awaitable[T]) -> tuple[T, Timing]:
    start = time.perf_counter()
    result = await call
    return result, Timing(label=label, seconds=time.perf_counter() - start)


def write_results(
    out_dir: Path, name: str, rows: Sequence[Mapping[str, str | int | float | None]]
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / name
    path.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"missing required environment variable: {name}")
    return value
