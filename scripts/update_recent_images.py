#!/usr/bin/env python3
"""Update cache of recent downloaded images.

This script collects the 200 most recently modified files in the
``downloads`` directory, filters them to include only images, and writes the
list of image filenames to ``logs/image_cache.json``. The file is rewritten on
each run so its modification timestamp reflects the last update.  The script
is intended to run after each download or on a schedule.
"""

import json
import os
from pathlib import Path
from typing import List

# Repository paths
REPO_ROOT = Path(__file__).resolve().parents[1]
DOWNLOAD_DIR = REPO_ROOT / "downloads"
LOG_DIR = REPO_ROOT / "logs"
CACHE_FILE = LOG_DIR / "image_cache.json"

# Extensions considered as images
IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".webp",
    ".tiff",
    ".svg",
}


def get_recent_files(directory: Path, limit: int = 200) -> List[Path]:
    """Return up to ``limit`` files in ``directory`` and subdirs sorted by mtime."""
    if not directory.exists():
        return []

    files = [f for f in directory.rglob("*") if f.is_file()]
    files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    return files[:limit]


def main() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    recent_files = get_recent_files(DOWNLOAD_DIR)
    images = [str(f.relative_to(DOWNLOAD_DIR)) for f in recent_files if f.suffix.lower() in IMAGE_EXTENSIONS]

    with CACHE_FILE.open("w", encoding="utf-8") as fh:
        json.dump(images, fh, indent=2)
        fh.write("\n")
    # Ensure modification time reflects update even if contents unchanged
    os.utime(CACHE_FILE, None)


if __name__ == "__main__":
    main()
