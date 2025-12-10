#!/usr/bin/env python3
import re
import subprocess
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) < 2:
        print("Error: No URL provided", file=sys.stderr)
        sys.exit(1)

    url = sys.argv[1]

    if not re.match(r"^https?://", url):
        print("Error: Invalid URL format", file=sys.stderr)
        sys.exit(1)

    download_dir = Path("/downloads")
    download_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "gallery-dl",
        "--dest",
        str(download_dir),
        "--verbose",
        "--no-part",
        url,
    ]

    print(f"Running: {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
    except subprocess.CalledProcessError as e:
        print(f"gallery-dl failed:\n{e.stderr}", file=sys.stderr)
        sys.exit(e.returncode)
    except FileNotFoundError:
        print("Error: gallery-dl not found. Ensure it's installed and in PATH.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
