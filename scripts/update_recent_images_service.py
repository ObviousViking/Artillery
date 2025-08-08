#!/usr/bin/env python3
"""Background service to update recent images cache periodically."""

import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "update_recent_images.py"
CACHE_FILE = REPO_ROOT / "logs" / "image_cache.json"
INTERVAL = 3600  # seconds


def run_update() -> None:
    """Execute the update_recent_images script."""
    subprocess.run([sys.executable, str(SCRIPT)], check=True)


def main() -> None:
    if not CACHE_FILE.exists():
        run_update()

    while True:
        run_update()
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
