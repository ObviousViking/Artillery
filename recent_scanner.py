import os
import time
import shutil
from pathlib import Path
from multiprocessing import Process

# --- media types -------------------------------------------------------------

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
VIDEO_EXTS = {".mp4", ".webm", ".mkv"}
MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS


def get_recent_media_files_streaming(
    download_root: str,
    limit: int = 100,
    max_top_dirs: int = 50,
    max_total_dirs: int = 200,
):
    """
    Streaming, bounded scan:

      1. Scan media files directly in download_root.
      2. Collect top-level subdirs and sort by mtime (newest first).
      3. For each top-level dir (in that order), do a DFS:
         - Use os.scandir() as an iterator (NO list()).
         - As we see files, we add media files immediately.
         - As soon as we hit `limit` total media files, we STOP and return.
         - We also cap total dirs visited at `max_total_dirs`.

    This avoids fully listing giant leaf directories just to grab 100 files.
    """
    root = Path(download_root)
    if not root.is_dir():
        print(f"Recent scanner: download root {download_root} is not a directory")
        return []

    print(
        "Recent scanner: streaming scan START "
        f"(root={download_root}, limit={limit}, "
        f"max_top_dirs={max_top_dirs}, max_total_dirs={max_total_dirs})"
    )

    results = []
    total_dirs = 0

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
                        print(f"Recent scanner: ROOT media -> {entry.name}")
                        if len(results) >= limit:
                            print(
                                "Recent scanner: collected "
                                f"{len(results)} files from ROOT (root_media={root_media_count}), stopping early"
                            )
                            return results
                elif entry.is_dir(follow_symlinks=False):
                    root_dir_count += 1
                    top_dirs.append((st.st_mtime, entry.path))
    except FileNotFoundError:
        print(f"Recent scanner: root {download_root} disappeared during scan")
        return results

    print(
        "Recent scanner: root scan done "
        f"(root_media={root_media_count}, top_dirs_found={root_dir_count})"
    )

    # 2) Sort top-level dirs by mtime (newest first), cap count
    top_dirs.sort(key=lambda x: x[0], reverse=True)
    original_top_dirs = len(top_dirs)
    top_dirs = [p for _, p in top_dirs[:max_top_dirs]]

    print(
        "Recent scanner: using "
        f"{len(top_dirs)}/{original_top_dirs} top-level dirs after cap"
    )

    # 3) For each top-level dir, do a bounded streaming DFS
    for idx, top_dir in enumerate(top_dirs, start=1):
        if len(results) >= limit:
            print(
                f"Recent scanner: already reached limit={limit} "
                f"before top_dir #{idx}"
            )
            break
        if total_dirs >= max_total_dirs:
            print(
                f"Recent scanner: hit max_total_dirs={max_total_dirs} "
                f"before top_dir #{idx}"
            )
            break

        print(
            "Recent scanner: starting DFS at top dir "
            f"#{idx}/{len(top_dirs)}: {top_dir} "
            f"(current_files={len(results)}, total_dirs={total_dirs})"
        )

        stack = [top_dir]

        while stack and len(results) < limit and total_dirs < max_total_dirs:
            current_dir = stack.pop()
            total_dirs += 1

            if total_dirs % 50 == 0:
                print(
                    "Recent scanner: progress – inspected "
                    f"{total_dirs} dirs so far (files={len(results)})"
                )

            try:
                it = os.scandir(current_dir)
            except (FileNotFoundError, NotADirectoryError, PermissionError, OSError):
                print(f"Recent scanner: skipping unreadable dir {current_dir}")
                continue

            # STREAM entries: do NOT wrap in list()
            for entry in it:
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                    is_file = entry.is_file(follow_symlinks=False)
                except OSError:
                    continue

                if is_file:
                    ext = os.path.splitext(entry.name)[1].lower()
                    if ext not in MEDIA_EXTS:
                        continue

                    try:
                        st = entry.stat()
                    except OSError:
                        continue

                    results.append(
                        {
                            "path": entry.path,
                            "name": entry.name,
                            "mtime": st.st_mtime,
                        }
                    )
                    print(f"Recent scanner: MEDIA file -> {entry.path}")

                    if len(results) >= limit:
                        print(
                            "Recent scanner: collected "
                            f"{len(results)} files, stopping in dir {current_dir} "
                            f"(total_dirs={total_dirs})"
                        )
                        return results

                elif is_dir:
                    # Defer deeper scanning; we don't sort by mtime here
                    stack.append(entry.path)

    print(
        "Recent scanner: finished streaming scan with "
        f"{len(results)} files (limit={limit}, total_dirs={total_dirs})"
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

    print(
        "Recent scanner: sync_temp_folder – "
        f"{len(desired_names)} desired files, removed {removed} obsolete files"
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
            print(f"Recent scanner: copied -> {src_path} -> {dst_path}")
        except FileNotFoundError:
            continue
        except Exception:
            continue

    print(
        "Recent scanner: sync_temp_folder – "
        f"copied {copied} new files into {temp_root_path}"
    )


def recent_scanner_loop(download_root: str, temp_root: str, interval_seconds: int = 3600, limit: int = 100):
    """
    Standalone loop: runs in a separate process.
    """
    print(
        "Recent scanner: loop started "
        f"(root={download_root}, temp={temp_root}, "
        f"interval={interval_seconds}s, limit={limit})"
    )

    while True:
        try:
            recent_files = get_recent_media_files_streaming(
                download_root,
                limit=limit,
                max_top_dirs=50,
                max_total_dirs=200,
            )

            sync_temp_folder(recent_files, temp_root)

            print(
                "Recent scanner: cycle COMPLETE, "
                f"{len(recent_files)} files in temp folder"
            )
        except Exception as exc:
            print(f"Recent scanner: cycle FAILED: {exc!r}")

        print(
            "Recent scanner: sleeping for "
            f"{interval_seconds} seconds"
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
        print(
            f"Recent scanner: lock file {lock_path} exists, "
            f"not starting another scanner"
        )
        return

    try:
        proc = Process(
            target=recent_scanner_loop,
            args=(download_root, temp_root),
            daemon=True,
        )
        proc.start()
        print(
            "Recent scanner: started subprocess "
            f"pid={proc.pid} (root={download_root}, temp={temp_root})"
        )
    except Exception as exc:
        print(f"Recent scanner: failed to start subprocess: {exc!r}")
