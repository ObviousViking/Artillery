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

    Extra logging has been added so you can see progress in the container logs.
    """
    root = Path(download_root)
    if not root.is_dir():
        logger.warning("Recent scanner: download root %s is not a directory", download_root)
        return []

    logger.warning(
        "Recent scanner: leaf-first scan START "
        "(root=%s, limit=%d, max_top_dirs=%d, max_total_dirs=%d, max_leaf_dirs=%d)",
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
    root_media_count = 0
    root_dir_count = 0

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
                        root_media_count += 1
                        results.append(
                            {
                                "path": os.path.join(download_root, entry.name),
                                "name": entry.name,
                                "mtime": st.st_mtime,
                            }
                        )
                        if len(results) >= limit:
                            logger.warning(
                                "Recent scanner: collected %d files from ROOT (root_media=%d), stopping early",
                                len(results),
                                root_media_count,
                            )
                            return results
                elif entry.is_dir(follow_symlinks=False):
                    root_dir_count += 1
                    top_dirs.append((st.st_mtime, entry.path))
    except FileNotFoundError:
        logger.warning("Recent scanner: root %s disappeared during scan", download_root)
        return results

    logger.warning(
        "Recent scanner: root scan done (root_media=%d, top_dirs_found=%d)",
        root_media_count,
        root_dir_count,
    )

    # 2) Sort top-level dirs by mtime (newest first), cap count
    top_dirs.sort(key=lambda x: x[0], reverse=True)
    original_top_dirs = len(top_dirs)
    top_dirs = [p for _, p in top_dirs[:max_top_dirs]]

    logger.warning(
        "Recent scanner: using %d/%d top-level dirs after cap",
        len(top_dirs),
        original_top_dirs,
    )

    # 3) For each top-level dir, do a bounded leaf-first DFS
    for idx, top_dir in enumerate(top_dirs, start=1):
        if len(results) >= limit:
            logger.warning("Recent scanner: already reached limit=%d before top_dir #%d", limit, idx)
            break
        if total_dirs >= max_total_dirs:
            logger.warning(
                "Recent scanner: hit max_total_dirs=%d before top_dir #%d",
                max_total_dirs,
                idx,
            )
            break
        if leaf_dirs_seen >= max_leaf_dirs:
            logger.warning(
                "Recent scanner: hit max_leaf_dirs=%d before top_dir #%d",
                max_leaf_dirs,
                idx,
            )
            break

        logger.warning(
            "Recent scanner: starting DFS at top dir #%d/%d: %s (current_files=%d, total_dirs=%d, leaf_dirs=%d)",
            idx,
            len(top_dirs),
            top_dir,
            len(results),
            total_dirs,
            leaf_dirs_seen,
        )

        stack = [top_dir]

        while (
            stack
            and len(results) < limit
            and total_dirs < max_total_dirs
            and leaf_dirs_seen < max_leaf_dirs
        ):
            current_dir = stack.pop()
            total_dirs += 1

            if total_dirs % 50 == 0:
                logger.warning(
                    "Recent scanner: progress – inspected %d dirs so far (leaf_dirs=%d, files=%d)",
                    total_dirs,
                    leaf_dirs_seen,
                    len(results),
                )

            try:
                entries = list(os.scandir(current_dir))
            except (FileNotFoundError, NotADirectoryError, PermissionError, OSError):
                logger.warning("Recent scanner: skipping unreadable dir %s", current_dir)
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
                    continue

            if not subdirs:
                # Leaf directory: only here do we look at files
                leaf_dirs_seen += 1

                logger.warning(
                    "Recent scanner: leaf dir #%d at %s (files_here=%d, total_files=%d)",
                    leaf_dirs_seen,
                    current_dir,
                    len(files),
                    len(results),
                )

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
                            "Recent scanner: collected %d files, stopping at leaf dir %s "
                            "(total_dirs=%d, leaf_dirs=%d)",
                            len(results),
                            current_dir,
                            total_dirs,
                            leaf_dirs_seen,
                        )
                        return results

                # done with this leaf; continue
            else:
                # Not a leaf yet: go deeper, most recent subdirs first
                try:
                    subdirs.sort(key=lambda e: e.stat().st_mtime, reverse=True)
                except OSError:
                    pass

                for sd in subdirs:
                    stack.append(sd.path)

    logger.warning(
        "Recent scanner: finished leaf-first scan with %d files "
        "(limit=%d, total_dirs=%d, leaf_dirs=%d)",
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
    removed = 0
    for existing in temp_root_path.iterdir():
        if existing.is_file() and existing.name not in desired_names:
            try:
                existing.unlink()
                removed += 1
            except Exception:
                pass

    logger.warning(
        "Recent scanner: sync_temp_folder – %d files remain, removed %d obsolete files",
        len(desired_names),
        removed,
    )

    # Ensure all desired files exist
    copied = 0
    for final_name, src_path in desired_map.items():
        dst_path = temp_root_path / final_name

        if dst_path.exists():
            continue

        try:
            shutil.copy2(src_path, dst_path)
            copied += 1
        except FileNotFoundError:
            continue
        except Exception:
            continue

    logger.warning(
        "Recent scanner: sync_temp_folder – copied %d new files into %s",
        copied,
        temp_root_path,
    )


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
                "Recent scanner: cycle COMPLETE, %d files in temp folder",
                len(recent_files),
            )
        except Exception as exc:
            logger.exception("Recent scanner: cycle FAILED: %s", exc)

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
