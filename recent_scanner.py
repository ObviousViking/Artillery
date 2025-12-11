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


def get_recent_leaf_media_files(
    download_root: str,
    limit: int = 100,
    max_top_dirs: int = 100,
    max_total_dirs: int = 400,
    max_leaf_dirs: int = 80,
):
    """
    Scan the downloads tree in a *very bounded* way:

      1. Collect media files directly in download_root.
      2. Collect top-level subdirs and sort by mtime (newest first).
      3. For each top-level dir (in that order), do a leaf-first DFS:
         - A directory with no subdirectories is treated as a "leaf".
         - Only files in leaf dirs are considered.
         - Stop as soon as:
             * we have `limit` media files, or
             * we've looked at `max_total_dirs` dirs total, or
             * we've looked at `max_leaf_dirs` leaf dirs.

    This keeps each scan small even on gigantic trees.
    """
    root = Path(download_root)
    if not root.is_dir():
        logger.warning("Recent scanner: download root %s is not a directory", download_root)
        return []

    logger.warning(
        "Recent scanner: leaf-first scan (root=%s, limit=%d, max_top_dirs=%d, max_total_dirs=%d, max_leaf_dirs=%d)",
        download_root,
        limit,
        max_top_dirs,
        max_total_dirs,
        max_leaf_dirs,
    )

    results = []
    total_dirs = 0
    leaf_dirs_seen = 0

    # 1) Media files directly in /downloads root
    top_dirs = []
    try:
        with os.scandir(download_root) as it:
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
                                "Recent scanner: collected %d files from root, stopping early",
                                len(results),
                            )
                            return results
                elif entry.is_dir(follow_symlinks=False):
                    top_dirs.append((st.st_mtime, entry.path))
    except FileNotFoundError:
        return results

    # 2) Sort top-level dirs by mtime (newest first), cap count
    top_dirs.sort(key=lambda x: x[0], reverse=True)
    top_dirs = [p for _, p in top_dirs[:max_top_dirs]]

    # 3) For each top-level dir, do a bounded leaf-first DFS
    for top_dir in top_dirs:
        if len(results) >= limit or total_dirs >= max_total_dirs or leaf_dirs_seen >= max_leaf_dirs:
            break

        logger.warning("Recent scanner: starting DFS at top dir %s", top_dir)
        stack = [top_dir]

        while stack and len(results) < limit and total_dirs < max_total_dirs and leaf_dirs_seen < max_leaf_dirs:
            current_dir = stack.pop()
            total_dirs += 1

            try:
                entries = list(os.scandir(current_dir))
            except (FileNotFoundError, NotADirectoryError, PermissionError, OSError):
                continue

            subdirs = []
            files = []

            for e in entries:
                try:
                    if e.is_dir(follow_symlinks=False):
                        subdirs.append(e)
                    elif e.is_file(follow_symlinks=False):
                        files.append(e)
                except OSError:
                    # just skip weird entries
                    continue

            if not subdirs:
                # Leaf directory: only here do we look at files
                leaf_dirs_seen += 1

                for f in files:
                    ext = os.path.splitext(f.name)[1].lower()
                    if ext not in MEDIA_EXTS:
                        continue

                    try:
                        st = f.stat()
                    except OSError:
                        continue

                    results.append(
                        {
                            "path": f.path,
                            "name": f.name,
                            "mtime": st.st_mtime,
                        }
                    )

                    if len(results) >= limit:
                        logger.warning(
                            "Recent scanner: collected %d files, stopping at leaf dir %s",
                            len(results),
                            current_dir,
                        )
                        return results

                # done with this leaf; continue with next on stack
            else:
                # Not a leaf yet: go deeper, most recent subdirs last in stack so they are popped first
                try:
                    subdirs.sort(key=lambda e: e.stat().st_mtime, reverse=True)
                except OSError:
                    # if stat fails, just leave unsorted
                    pass

                for sd in subdirs:
                    stack.append(sd.path)

    logger.warning(
        "Recent scanner: finished leaf-first scan with %d files (limit=%d, total_dirs=%d, leaf_dirs=%d)",
        len(results),
        limit,
        total_dirs,
        leaf_dirs_seen,
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
            recent_files = get_recent_leaf_media_files(
                download_root,
                limit=limit,
                max_top_dirs=100,
                max_total_dirs=400,
                max_leaf_dirs=80,
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
