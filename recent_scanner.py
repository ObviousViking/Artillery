import os
import time
import shutil
import random
from pathlib import Path
from datetime import datetime
from flask import current_app

# Define media extensions here so we only sample media-ish files
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
VIDEO_EXTS = {".mp4", ".webm", ".mkv"}
MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS

# Optional: in-memory cache if you want to read metadata from Python
recent_cache = {
    "last_run": None,
    "files": [],  # list of dicts: {"path": "...", "name": "...", "mtime": ...}
}


def get_recent_files(download_root: str, limit: int = 100):
    """
    RANDOM SAMPLER NOW (name kept for compatibility).

    Walk the download_root and return `limit` random media files.
    Uses reservoir sampling so memory stays small even if the tree is huge.
    """
    download_root = Path(download_root)

    reservoir = []  # up to `limit` entries
    seen = 0

    for dirpath, dirnames, filenames in os.walk(download_root):
        for name in filenames:
            full_path = Path(dirpath) / name

            ext = full_path.suffix.lower()
            if ext not in MEDIA_EXTS:
                continue

            try:
                stat = full_path.stat()
            except FileNotFoundError:
                # It might be deleted between walk and stat; just skip
                continue

            entry = {
                "path": str(full_path),
                "name": full_path.name,
                "mtime": stat.st_mtime,
            }

            seen += 1
            if len(reservoir) < limit:
                reservoir.append(entry)
            else:
                # Reservoir sampling: replace existing entry with decreasing probability
                j = random.randint(0, seen - 1)
                if j < limit:
                    reservoir[j] = entry

    return reservoir


def sync_temp_folder(recent_files, temp_root: str):
    """
    Mirror `recent_files` into temp_root as **copies** (no symlinks).
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

        if dst_path.exists():
            # For now, assume it's fine; we could compare mtimes if we want.
            continue

        try:
            shutil.copy2(src_path, dst_path)
        except FileNotFoundError:
            # Source disappeared, skip
            continue
        except Exception:
            # Ignore other failures; this is best-effort eye candy
            continue


def recent_scanner_loop(app, interval_seconds: int = 3600, limit: int = 100):
    """
    Background loop that runs forever:
    - walks the download dir
    - selects `limit` random media files
    - mirrors them into the media wall folder
    """
    with app.app_context():
        while True:
            try:
                download_root = current_app.config["DOWNLOAD_DIR"]
                temp_root = current_app.config["RECENT_TEMP_DIR"]

                current_app.logger.warning(
                    "Recent scanner: starting scan (root=%s, temp=%s)",
                    download_root,
                    temp_root,
                )
                recent_files = get_recent_files(download_root, limit=limit)

                current_app.logger.warning(
                    "Recent scanner: sampled %d random media files",
                    len(recent_files),
                )

                sync_temp_folder(recent_files, temp_root)

                # Update cache (optional)
                recent_cache["last_run"] = datetime.utcnow().timestamp()
                recent_cache["files"] = recent_files

                current_app.logger.warning(
                    "Recent scanner: cycle complete for root %s", download_root
                )
            except Exception as e:
                current_app.logger.exception("Recent scanner failed: %s", e)

            current_app.logger.warning(
                "Recent scanner: sleeping for %d seconds.", interval_seconds
            )
            time.sleep(interval_seconds)


def start_recent_scanner(app):
    """
    Start the background thread once.
    """
    import threading

    if getattr(app, "_recent_scanner_started", False):
        # Avoid starting multiple scanner threads per process
        return

    app._recent_scanner_started = True

    app.logger.warning("Recent scanner: starting background thread")

    t = threading.Thread(
        target=recent_scanner_loop,
        args=(app,),
        daemon=True,
    )
    t.start()
