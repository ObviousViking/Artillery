# recent_scanner.py
import os
import time
from flask import current_app

from pathlib import Path

# ... your existing get_recent_files / sync_temp_folder ...

def _get_interval_seconds():
    cfg_path = current_app.config.get("SCAN_INTERVAL_FILE")
    default_minutes = current_app.config.get("DEFAULT_SCAN_INTERVAL_MINUTES", 60)

    if not cfg_path or not os.path.exists(cfg_path):
        return default_minutes * 60

    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            raw = f.read().strip()
        minutes = int(raw)
    except Exception:
        return default_minutes * 60

    minutes = max(5, min(minutes, 1440))
    return minutes * 60


def recent_scanner_loop(app, limit: int = 100):
    with app.app_context():
        while True:
            try:
                download_root = current_app.config["DOWNLOAD_DIR"]
                temp_root = current_app.config["RECENT_TEMP_DIR"]

                current_app.logger.info("Recent scanner: starting scan.")
                recent_files = get_recent_files(download_root, limit=limit)
                sync_temp_folder(recent_files, temp_root)
                current_app.logger.info(
                    "Recent scanner: completed. %d files mirrored.",
                    len(recent_files),
                )
            except Exception as e:
                current_app.logger.exception("Recent scanner failed: %s", e)

            time.sleep(_get_interval_seconds())


def start_recent_scanner(app):
    import threading

    if getattr(app, "_recent_scanner_started", False):
        return

    app._recent_scanner_started = True

    t = threading.Thread(
        target=recent_scanner_loop,
        args=(app,),
        daemon=True,
    )
    t.start()
