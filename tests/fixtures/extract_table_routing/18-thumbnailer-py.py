"""Thumbnail helper: shells out to ImageMagick and keeps a small in-memory cache."""

from __future__ import annotations

import subprocess
from pathlib import Path

_CACHE: dict[str, bytes] = {}
MAX_SIDE = 512


def is_supported(path: Path) -> bool:
    """Whether the file has an extension the converter accepts."""
    return path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}


def build_command(source: Path, target: Path) -> list[str]:
    """The ImageMagick call that writes the thumbnail."""
    return ["magick", "convert", str(source), "-resize", f"{MAX_SIDE}x{MAX_SIDE}", str(target)]


def make_thumbnail(source: Path, target: Path) -> bytes:
    """Create the thumbnail once and answer from the cache afterwards."""
    key = str(source)
    if key not in _CACHE:
        subprocess.run(build_command(source, target), check=True, timeout=30)
        _CACHE[key] = target.read_bytes()
    return _CACHE[key]
