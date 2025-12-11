import os
import time
import shutil
import random
import logging
from pathlib import Path
from multiprocessing import Process

# --- media types -------------------------------------------------------------

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
VIDEO_EXTS = {".mp4", ".webm", ".mkv"}
MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS

logger = logging.getLogger("recent_scanner")


def get_random_media_files(
    download_root: str,
    limit: int = 100,
    max_candidates: int = 5000,
    max_top_dirs: int = 50,
):
    """
    Fast-ish random sampler over a huge downloads tree.

    Strategy:
      - Look at the most recently modified top-level dirs under download_root.
      - Walk only those, and stop after seeing at most `max_candidates` media files.
      - Use reservoir sampling to get up to `limit` random media files from that
        subset without keeping everything in memory.
    """
    root = Path(download_root)
    if not root.is_dir():
        logger.warning("Recent scanner: download root %s is not a directory", download_root)
        return []

    logger.warning(
        "Recent scanner: sampling random media files (root=%s, limit=%d, max_candidates=%d, max_top_dirs=%d)",
        download_root,
        limit,
        max_candidates,
        max_top_dirs,
    )

    # Collect top-level dirs + root files
    top_dirs = []
    root_files = []

    try:
        with os.scandir(download_root) as it:
            for entry in it:
                try:
                    st = entry.stat()
                except OSError:
                    continue

                if entry.is_dir(follow_symlinks=False):
                    top_dirs.append((st.st_mtime, entry.path))
                elif entry.is_file(follow_symlinks=False):
                    # Allow loose media files directly in root
                    ext = os.path.splitext(entry.name)[1].lower()
                    if ext in MEDIA_EXTS:
                        root_files.append(
                            {
                                "path": os.path.join(download_root, entry.name),
                                "name": entry.name,
                                "mtime": st.st_mtime,
                            }
                        )
    except FileNotFoundError:
        return []

    # Newest top-level dirs first
    top_dirs.sort(key=lambda x: x[0], reverse=True)
    top_dirs = [p for _, p in top_dirs[:max_top_dirs]]

    reservoir = []
    seen = 0

    # First, consider root media files (if any)
    for f in root_files:
        seen += 1
        if len(reservoir) < limit:
            reservoir.append(f)
        else:
            j = random.randint(0, seen - 1)
            if j < limit:
                reservoir[j] = f

        if seen >= max_candidates:
            logger.warning(
                "Recent scanner: early stop after %d candidates (root files only)",
                seen,
            )
            return reservoir

    # Then, walk selected top-level dirs, but stop after max_candidates media files
    stop = False
    for base_dir in top_dirs:
        if stop:
            break

        for dirpath, dirnames, filenames in os.walk(base_dir):
            for name in filenames:
                ext = os.path.splitext(name)[1].lower()
                if ext not in MEDIA_EXTS:
                    continue

                full_path = Path(dirpath) / name
                try:
                    st = full_path.stat()
                except OSError:
                    continue

                entry = {
                    "path": str(full_path),
                    "name": full_path.name,
                    "mtime": st.st_mtime,
                }

                seen += 1
                if len(reservoir) < limit:
                    reservoir.append(entry)
                else:
                    j = random.randint(0, seen - 1)
                    if j < limit:
                        reservoir[j] = entry

                if seen >= max_candidates:
                    logger.warning(
                        "Recent scanner: early stop after %d candidate media files",
                        seen,
                    )
                    stop = True
                    break

            if stop:
                break

    logger.warning(
        "Recent scanner: sampled %d media files from %d candidates",
        len(reservoir),
        seen,
    )
    return reservoir


def sync_temp_folder(recent_files, temp_root: str):
    """
    Mirror `recent_files` into temp_root as **copies**.
    - Deletes files from temp_root that are no longer in recent_files.
    """
    temp_root_path = Path(temp_root)
    temp_root_path.mkdir(parents=True, exist_ok=True)

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
    for existing in temp_root_path.iterdir():
        if existing.is_file() and existing.name not in desired_names:
            try:
                existing.unlink()
            except Exception:
                pass

    # Ensure all desired files exist
    for final_name, src_path in desired_map.items():
        dst_path = temp_root_path / final_name

        if dst_path.exists():
            continue

        try:
            shutil.copy2(src_path, dst_path)
        except FileNotFoundError:
            continue
        except Exception:
            continue


def recent_scanner_loop(download_root: str, temp_root: str, interval_seconds: int = 3600, limit: int = 100):
    """
    Standalone loop: runs in a separate process.
    """
    logger.warning(
        "Recent scanner: loop started (root=%s, temp=%s, interval=%ds, limit=%d)",
        download_root,
        temp_root,
        interval_seconds,
        limit,
    )

    while True:
        try:
            recent_files = get_random_media_files(
                download_root,
                limit=limit,
                max_candidates=5000,
                max_top_dirs=50,
            )

            sync_temp_folder(recent_files, temp_root)

            logger.warning(
                "Recent scanner: cycle complete, %d files in temp folder",
                len(recent_files),
            )
        except Exception as exc:
            logger.exception("Recent scanner: cycle failed: %s", exc)

        logger.warning(
            "Recent scanner: sleeping for %d seconds",
            interval_seconds,
        )
        time.sleep(interval_seconds)


def start_recent_scanner(app):
    """
    Start the background scanner in a **separate process** so it can't block
    the Flask/Gunicorn worker, even on huge download trees.

    We also use a simple lockfile in /tmp to avoid starting multiple scanners
    if there are several worker processes.
    """
    download_root = app.config.get("DOWNLOAD_DIR", "/downloads")
    temp_root = app.config.get("RECENT_TEMP_DIR")

    if not temp_root:
        # Fallback, should already be configured in app.py
        config_root = os.environ.get("CONFIG_DIR", "/config")
        temp_root = os.path.join(config_root, "media_wall")

    lock_path = os.environ.get("RECENT_SCANNER_LOCK", "/tmp/recent_scanner.lock")

    # Simple "only start once per container" lock
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
        have_lock = True
    except FileExistsError:
        have_lock = False

    if not have_lock:
        logger.warning("Recent scanner: lock file %s exists, not starting another scanner", lock_path)
        return

    try:
        proc = Process(
            target=recent_scanner_loop,
            args=(download_root, temp_root),
            daemon=True,
        )
        proc.start()
        logger.warning(
            "Recent scanner: started subprocess pid=%s (root=%s, temp=%s)",
            proc.pid,
            download_root,
            temp_root,
        )
    except Exception as exc:
        logger.exception("Recent scanner: failed to start subprocess: %s", exc)
