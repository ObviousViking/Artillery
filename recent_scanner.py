# recent_scanner.py
import os
import time
import shutil
from pathlib import Path
from datetime import datetime

from flask import current_app


def get_recent_files(download_root: str, limit: int = 100):
    """
    Walk the download_root and return the `limit` most recently modified files.
    """
    download_root = Path(download_root)

    file_entries = []
    for dirpath, dirnames, filenames in os.walk(download_root):
        for name in filenames:
            full_path = Path(dirpath) / name
            try:
                stat = full_path.stat()
            except FileNotFoundError:
                # It might be deleted between walk and stat; just skip
                continue

            file_entries.append((stat.st_mtime, full_path))

    # Sort newest first and slice
    file_entries.sort(key=lambda x: x[0], reverse=True)
    file_entries = file_entries[:limit]

    result = []
    for mtime, path in file_entries:
        result.append(
            {
                "path": str(path),
                "name": path.name,
                "mtime": mtime,
            }
        )

    return result


def sync_temp_folder(recent_files, temp_root: str, use_symlinks: bool = True):
    """
    Mirror `recent_files` into temp_root as copies or symlinks.
    - Deletes files from temp_root that are no longer in recent_files.
    """
    temp_root = Path(temp_root)
    temp_root.mkdir(parents=True, exist_ok=True)

    # Target names: just use the basename, but de-duplicate if necessary
    desired_map = {}  # final_name -> source_path

    name_counts = {}
    for f in recent_files:
        base = f["name"]
        if base not in name_counts:
            name_counts[base] = 0
            final_name = base
        else:
            name_counts[base] += 1
            stem = Path(base).stem
            suffix = Path(base).suffix
            final_name = f"{stem}_{name_counts[base]}{suffix}"

        desired_map[final_name] = f["path"]

    desired_names = set(desired_map.keys())

    # Remove obsolete files from temp_root
    for existing in temp_root.iterdir():
        if existing.is_file() and existing.name not in desired_names:
            try:
                existing.unlink()
            except Exception:
                pass

    # Ensure all desired files exist / updated
    for final_name, src_path in desired_map.items():
        dst_path = temp_root / final_name

        if dst_path.exists():
            # You *could* compare mtimes here if you want, but for now skip
            continue

        try:
            if use_symlinks:
                try:
                    if dst_path.exists() or dst_path.is_symlink():
                        dst_path.unlink()
                    os.symlink(src_path, dst_path)
                except OSError:
                    shutil.copy2(src_path, dst_path)
            else:
                shutil.copy2(src_path, dst_path)
        except FileNotFoundError:
            # Source disappeared, skip
            continue


def _get_interval_seconds() -> int:
    """
    Read the interval (minutes) from SCAN_INTERVAL_FILE,
    falling back to DEFAULT_SCAN_INTERVAL_MINUTES, and clamp to 5–1440 mins.
    """
    cfg_path = current_app.config.get("SCAN_INTERVAL_FILE")
    default_minutes = current_app.config.get("DEFAULT_SCAN_INTERVAL_MINUTES", 60)

    # default
    minutes = default_minutes

    if cfg_path and os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                raw = f.read().strip()
            minutes = int(raw)
        except Exception:
            minutes = default_minutes

    minutes = max(5, min(minutes, 1440))
    return minutes * 60


def recent_scanner_loop(app, limit: int = 100):
    """
    Background loop that:
      - scans DOWNLOAD_DIR
      - mirrors up to `limit` most recent files into RECENT_TEMP_DIR
      - sleeps based on SCAN_INTERVAL_FILE
    """
    with app.app_context():
        while True:
            try:
                download_root = current_app.config["DOWNLOAD_DIR"]
                temp_root = current_app.config["RECENT_TEMP_DIR"]

                current_app.logger.info("Recent scanner: starting scan.")
                recent_files = get_recent_files(download_root, limit=limit)
                sync_temp_folder(recent_files, temp_root)
                current_app.logger.info(
                    "Recent scanner: completed. %d files mirrored.", len(recent_files)
                )
            except Exception as e:
                current_app.logger.exception("Recent scanner failed: %s", e)

            # Sleep based on current config file contents
            interval_seconds = _get_interval_seconds()
            current_app.logger.info(
                "Recent scanner: sleeping for %d seconds.", interval_seconds
            )
            time.sleep(interval_seconds)


def start_recent_scanner(app):
    """
    Start the background thread once.
    """
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
