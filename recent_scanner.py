"""
Temporary stub of recent_scanner.

All real scanning is disabled so the UI can't be slowed down by huge
downloads directories. We'll re-enable / rework this logic later.
"""

import os


def start_recent_scanner(app):
    """
    Called from app.py, but intentionally does nothing heavy.

    It just logs that the scanner is paused so you can see it in the
    container logs and confirm it's not running.
    """
    download_root = app.config.get("DOWNLOAD_DIR", "/downloads")
    temp_root = app.config.get("RECENT_TEMP_DIR") or os.path.join(
        os.environ.get("CONFIG_DIR", "/config"),
        "media_wall",
    )

    print(
        "Recent scanner: PAUSED – background scanning is disabled.\n"
        f"Recent scanner: would have used download root: {download_root}\n"
        f"Recent scanner: would have used media_wall dir: {temp_root}",
        flush=True,
    )
