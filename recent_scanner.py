import os
import time
import shutil
from pathlib import Path
from datetime import datetime
from flask import current_app

# Optional: in-memory cache if you want to read metadata from Python
recent_cache = {
    "last_run": None,
    "files": [],  # list of dicts: {"path": "...", "name": "...", "mtime": ...}
}


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

            file_entries.append(
                (stat.st_mtime, full_path)
            )

    # Sort newest first and slice
    file_entries.sort(key=lambda x: x[0], reverse=True)
    file_entries = file_entries[:limit]

    # Turn into nice dicts
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
                # Ignore failures for now
                pass

    # Ensure all desired files exist / updated
    for final_name, src_path in desired_map.items():
        dst_path = temp_root / final_name

        # If exists, you could check mtime and skip if up-to-date.
        if dst_path.exists():
            continue

        try:
            if use_symlinks:
                # Try symlink; if it fails (e.g. platform restriction), fall back to copy
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


def recent_scanner_loop(app, interval_seconds: int = 3600, limit: int = 100):
    """
    Background loop that runs forever:
    - scans the download dir
    - mirrors 100 most recent files into temp dir
    """
    with app.app_context():
        while True:
            try:
                download_root = current_app.config["DOWNLOAD_DIR"]
                temp_root = current_app.config["RECENT_TEMP_DIR"]

                current_app.logger.info("Recent scanner: starting scan.")
                recent_files = get_recent_files(download_root, limit=limit)

                sync_temp_folder(recent_files, temp_root)

                # Update cache (optional, if you want to render from Python)
                recent_cache["last_run"] = datetime.utcnow().timestamp()
                recent_cache["files"] = recent_files

                current_app.logger.info(
                    "Recent scanner: completed. %d files mirrored.",
                    len(recent_files),
                )
            except Exception as e:
                current_app.logger.exception("Recent scanner failed: %s", e)

            # Sleep until next run
            time.sleep(interval_seconds)


def start_recent_scanner(app):
    """
    Start the background thread once.
    Put this in your app factory.
    """
    import threading

    if getattr(app, "_recent_scanner_started", False):
        # Avoid starting multiple scanner threads per process
        return

    app._recent_scanner_started = True

    t = threading.Thread(
        target=recent_scanner_loop,
        args=(app,),
        daemon=True,
    )
    t.start()