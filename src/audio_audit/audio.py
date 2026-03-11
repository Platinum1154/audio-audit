from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
import datetime as dt
import os

from mutagen import File as MutagenFile


REMOVED_FOLDER_NAME = "_audit_removed"

AUDIO_EXTENSIONS = {
    ".aac",
    ".aif",
    ".aiff",
    ".flac",
    ".m4a",
    ".mp3",
    ".ogg",
    ".opus",
    ".wav",
    ".wma",
}

DEFAULT_LABELS = [
    "噪声",
    "静音",
    "人声异常",
    "截断",
    "爆音",
    "重复",
    "格式问题",
    "其他",
]


@dataclass(slots=True)
class ScannedAudio:
    absolute_path: Path
    relative_path: Path
    duration_seconds: float | None
    size_bytes: int


def scan_audio_files(root_path: Path) -> list[ScannedAudio]:
    items: list[ScannedAudio] = []

    for current_root, dir_names, file_names in os.walk(root_path):
        dir_names[:] = sorted(
            name for name in dir_names if name != REMOVED_FOLDER_NAME
        )

        current_root_path = Path(current_root)
        for file_name in sorted(file_names):
            absolute_path = current_root_path / file_name
            if absolute_path.suffix.lower() not in AUDIO_EXTENSIONS:
                continue

            try:
                size_bytes = absolute_path.stat().st_size
            except OSError:
                continue

            items.append(
                ScannedAudio(
                    absolute_path=absolute_path,
                    relative_path=absolute_path.relative_to(root_path),
                    duration_seconds=probe_duration_seconds(absolute_path),
                    size_bytes=size_bytes,
                )
            )

    return items


def probe_duration_seconds(path: Path) -> float | None:
    try:
        parsed = MutagenFile(path)
    except Exception:
        return None

    if parsed is None or getattr(parsed, "info", None) is None:
        return None

    length = getattr(parsed.info, "length", None)
    if length is None:
        return None

    try:
        return round(float(length), 3)
    except (TypeError, ValueError):
        return None


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "--:--"

    total_seconds = max(float(seconds), 0.0)
    minutes = int(total_seconds // 60)
    secs = int(total_seconds % 60)
    tenths = int((total_seconds - int(total_seconds)) * 10)
    return f"{minutes:02d}:{secs:02d}.{tenths}"


def normalize_labels(labels: Iterable[str], *, limit: int = 9) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for raw_label in labels:
        label = str(raw_label).strip()
        if not label or label in seen:
            continue
        seen.add(label)
        result.append(label[:32])
        if len(result) >= limit:
            break

    return result


def build_removed_path(root_path: Path, relative_path: Path) -> Path:
    return root_path / REMOVED_FOLDER_NAME / relative_path


def unique_destination(path: Path) -> Path:
    if not path.exists():
        return path

    timestamp = dt.datetime.now(dt.UTC).strftime("%Y%m%d%H%M%S")
    stem = path.stem
    suffix = path.suffix

    for index in range(1, 10_000):
        candidate = path.with_name(f"{stem}__{timestamp}_{index}{suffix}")
        if not candidate.exists():
            return candidate

    raise RuntimeError(f"Unable to generate unique destination for {path}")
