import os
import time
import shutil
from pathlib import Path
from multiprocessing import Process

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
VIDEO_EXTS = {".mp4", ".webm", ".mkv"}
MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS


def find_newest_leaf_dir(root: str, max_depth: int = 10) -> str | None:
    """
    Starting from `root`, repeatedly:
      - list direct subdirectories (no recursion),
      - pick the one with the newest mtime,
      - descend into it.

    Stop when:
      - there are no subdirectories (leaf), or
      - max_depth is reached, or
      - something goes wrong.

    Returns the path to the chosen leaf directory, or None.
    """
    current = Path(root)

    if not current.is_dir():
        print(f"Recent scanner: {root} is not a directory")
        return None

    print(f"Recent scanner: find_newest_leaf_dir start at {current}")

    depth = 0
    while depth < max_depth:
        try:
            subdirs = []
            with os.scandir(current) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            subdirs.append(entry)
                    except OSError:
                        continue
        except (FileNotFoundError, NotADirectoryError, PermissionError, OSError):
            print(f"Recent scanner: cannot list {current}, stopping descent")
            break

        if not subdirs:
            # No more subdirectories -> we consider this a leaf
            print(f"Recent scanner: reached leaf dir {current} at depth {depth}")
            return str(current)

        # Pick newest subdir by mtime
        try:
            newest = max(subdirs, key=lambda e: e.stat().st_mtime)
        except OSError:
            # If stat fails for some, just bail out with current as leaf
            print(f"Recent scanner: error reading mtimes in {current}, using it as leaf")
            return str(current)

        print(
            f"Recent scanner: depth {depth} -> choosing newest subdir {newest.path}"
        )

        current = Path(newest.path)
        depth += 1

    print(f"Recent scanner: max_depth reached at {current}")
    return str(current)


def collect_media_files_from_dir(dir_path: str, limit: int = 100):
    """
    Scan a single directory (non-recursive) for media files.
    Stop as soon as `limit` files have been collected.
    """
    results = []
    dir_path = Path(dir_path)

    if not dir_path.is_dir():
        print(f"Recent scanner: {dir_path} is not a directory when collecting media")
        return results

    print(
        f"Recent scanner: collecting up to {limit} media files from {dir_path}"
    )

    try:
        with os.scandir(dir_path) as it:
            for entry in it:
                try:
                    if not entry.is_file(follow_symlinks=False):
                        continue
                except OSError:
                    continue

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
                        f"Recent scanner: reached limit {limit} in {dir_path}, stopping"
                    )
                    break
    except (FileNotFoundError, NotADirectoryError, PermissionError, OSError):
        print(f"Recent scanner: could not scan files in {dir_path}")

    print(
        f"Recent scanner: collected {len(results)} media files from {dir_path}"
    )
    return results


def sync_temp_folder(recent_files, temp_root: str):
    """
    Mirror `recent_files` into temp_root as **copies**.
    - Deletes files from temp_root that are no longer in recent_files.
    """
    temp_root_path = Path(temp_root)
    temp_root_path.mkdir(parents=True, exist_ok=True)

    # Target names: use basename, de-duplicate if clashes
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


def recent_scanner_cycle(download_root: str, temp_root: str, limit: int = 100):
    """
    One full scanner cycle:
      - find newest leaf directory under download_root,
      - collect up to `limit` media files from *that one* directory,
      - sync them into temp_root.
    """
    print(
        f"Recent scanner: cycle start (root={download_root}, temp={temp_root}, limit={limit})"
    )

    leaf_dir = find_newest_leaf_dir(download_root, max_depth=10)
    if not leaf_dir:
        print("Recent scanner: no leaf dir found, skipping cycle")
        return

    media_files = collect_media_files_from_dir(leaf_dir, limit=limit)
    sync_temp_folder(media_files, temp_root)

    print(
        f"Recent scanner: cycle COMPLETE, {len(media_files)} files mirrored "
        f"from {leaf_dir} to {temp_root}"
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
            recent_scanner_cycle(download_root, temp_root, limit=limit)
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
