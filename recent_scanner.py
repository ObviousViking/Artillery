import os
import time
import shutil
import logging
from pathlib import Path
from multiprocessing import Process

# --- media types -------------------------------------------------------------

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
VIDEO_EXTS = {".mp4", ".webm", ".mkv"}
MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS

logger = logging.getLogger("recent_scanner")


def get_recent_media_files(
    download_root: str,
    limit: int = 100,
    max_top_dirs: int = 200,
):
    """
    Scan the downloads root in a *bounded* way:

      1. Look at media files directly in download_root.
      2. List top-level subdirectories and sort them by mtime (newest first).
      3. Walk each directory (recursively) in that order.
      4. Stop as soon as we've collected `limit` media files.

    This means:
      - On huge trees with recent active folders, we only touch a few dirs.
      - We never walk the entire 2M-file tree unless it's all cold / empty.
    """
    root = Path(download_root)
    if not root.is_dir():
        logger.warning("Recent scanner: download root %s is not a directory", download_root)
        return []

    logger.warning(
        "Recent scanner: scanning most recent folders (root=%s, limit=%d, max_top_dirs=%d)",
        download_root,
        limit,
        max_top_dirs,
    )

    results = []

    # 1) Media files directly in root
    try:
        with os.scandir(download_root) as it:
            top_dirs = []
            for entry in it:
                try:
                    st = entry.stat()
                except OSError:
                    continue

                if entry.is_file(follow_symlinks=False):
                    ext = os.path.splitext(entry.name)[1].lower()
                    if ext in MEDIA_EXTS:
                        results.append(
                            {
                                "path": os.path.join(download_root, entry.name),
                                "name": entry.name,
                                "mtime": st.st_mtime,
                            }
                        )
                        if len(results) >= limit:
                            logger.warning(
                                "Recent scanner: collected %d files from root, stopping",
                                len(results),
                            )
                            return results
                elif entry.is_dir(follow_symlinks=False):
                    # collect dirs for later, with their mtime
                    top_dirs.append((st.st_mtime, entry.path))
    except FileNotFoundError:
        return results

    # 2) Sort top-level dirs by mtime (newest first), limit how many we consider
    top_dirs.sort(key=lambda x: x[0], reverse=True)
    top_dirs = [p for _, p in top_dirs[:max_top_dirs]]

    # 3) Walk each directory in order, stopping as soon as we have `limit` files
    for dir_path in top_dirs:
        logger.warning("Recent scanner: walking dir %s", dir_path)
        for dirpath, dirnames, filenames in os.walk(dir_path):
            for name in filenames:
                ext = os.path.splitext(name)[1].lower()
                if ext not in MEDIA_EXTS:
                    continue

                full_path = Path(dirpath) / name
                try:
                    st = full_path.stat()
                except OSError:
                    continue

                results.append(
                    {
                        "path": str(full_path),
                        "name": full_path.name,
                        "mtime": st.st_mtime,
                    }
                )

                if len(results) >= limit:
                    logger.warning(
                        "Recent scanner: collected %d files, stopping at dir %s",
                        len(results),
                        dir_path,
                    )
                    return results

    logger.warning(
        "Recent scanner: finished scan with %d files total (limit=%d)",
        len(results),
        limit,
    )
    return results


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
            recent_files = get_recent_media_files(
                download_root,
                limit=limit,
                max_top_dirs=200,
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
