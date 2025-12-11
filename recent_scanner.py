import os
import time
import shutil
from pathlib import Path

from flask import current_app


def get_recent_files(
    download_root: str,
    limit: int = 100,
    max_top_dirs: int = 30,
    max_age_days: int = 30,
):
    """
    Faster scanner:

    - Only looks at the most recently modified top-level dirs under download_root
      (up to max_top_dirs).
    - Within those, prunes subdirs older than max_age_days.
    - Stops walking once we've collected `limit` files.
    """
    download_root = Path(download_root)

    # VERY noisy debug
    msg = f"Recent scanner: get_recent_files start (root={download_root})"
    print(msg, flush=True)
    current_app.logger.warning(msg)

    if not download_root.is_dir():
        msg = f"Recent scanner: download root {download_root} is not a directory"
        print(msg, flush=True)
        current_app.logger.warning(msg)
        return []

    now = time.time()
    max_age_seconds = max_age_days * 24 * 60 * 60
    cutoff = now - max_age_seconds

    file_entries = []

    # 1) Top-level dirs under /downloads, sorted by mtime (newest first)
    top_dirs = []
    try:
        for entry in os.scandir(download_root):
            try:
                st = entry.stat()
            except OSError:
                continue

            if entry.is_dir(follow_symlinks=False):
                top_dirs.append((st.st_mtime, entry.path))
            else:
                # Also consider files directly under /downloads
                file_entries.append((st.st_mtime, Path(entry.path)))
    except FileNotFoundError:
        msg = f"Recent scanner: download root {download_root} not found"
        print(msg, flush=True)
        current_app.logger.warning(msg)
        return []

    # Sort and trim top-level dirs
    top_dirs.sort(key=lambda x: x[0], reverse=True)
    top_dirs = [p for _, p in top_dirs[:max_top_dirs]]

    msg = (
        f"Recent scanner: {len(top_dirs)} top-level dirs selected, "
        f"{len(file_entries)} root files already"
    )
    print(msg, flush=True)
    current_app.logger.warning(msg)

    # If we already have enough from root files, we can skip walking
    if len(file_entries) >= limit:
        msg = f"Recent scanner: enough files from root only ({len(file_entries)})"
        print(msg, flush=True)
        current_app.logger.warning(msg)
        return _entries_to_results(file_entries, limit)

    # 2) Walk only those recent top-level directories
    for base_dir in top_dirs:
        for root, dirs, files in os.walk(base_dir):
            # Prune subdirectories that haven't been touched in a while
            pruned_dirs = []
            for d in list(dirs):
                d_path = os.path.join(root, d)
                try:
                    d_mtime = os.path.getmtime(d_path)
                except OSError:
                    pruned_dirs.append(d)
                    continue
                if d_mtime < cutoff:
                    pruned_dirs.append(d)

            # Remove pruned dirs from traversal
            for d in pruned_dirs:
                if d in dirs:
                    dirs.remove(d)

            # Collect files
            for fname in files:
                full_path = os.path.join(root, fname)
                try:
                    mtime = os.path.getmtime(full_path)
                except OSError:
                    continue

                file_entries.append((mtime, Path(full_path)))

                # If we already have limit files, no need to keep going
                if len(file_entries) >= limit:
                    break

            if len(file_entries) >= limit:
                break

        if len(file_entries) >= limit:
            break

    msg = f"Recent scanner: collected {len(file_entries)} candidate files"
    print(msg, flush=True)
    current_app.logger.warning(msg)

    return _entries_to_results(file_entries, limit)


def _entries_to_results(file_entries, limit):
    # Sort newest first and trim to limit
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

    msg = f"Recent scanner: sync_temp_folder with {len(recent_files)} files into {temp_root}"
    print(msg, flush=True)
    current_app.logger.warning(msg)

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
            # You could compare mtimes here if you want, but we skip for now
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

    minutes = default_minutes

    if cfg_path and os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                raw = f.read().strip()
            minutes = int(raw)
        except Exception:
            minutes = default_minutes

    minutes = max(5, min(minutes, 1440))
    seconds = minutes * 60

    msg = f"Recent scanner: interval is {minutes} minutes ({seconds} seconds)"
    print(msg, flush=True)
    current_app.logger.warning(msg)

    return seconds


def recent_scanner_loop(app, limit: int = 100):
    """
    Background loop that:
      - scans DOWNLOAD_DIR (but only recent top-level dirs)
      - mirrors up to `limit` most recent files into RECENT_TEMP_DIR
      - sleeps based on SCAN_INTERVAL_FILE
    """
    with app.app_context():
        msg = "Recent scanner: loop started"
        print(msg, flush=True)
        current_app.logger.warning(msg)

        while True:
            try:
                download_root = current_app.config["DOWNLOAD_DIR"]
                temp_root = current_app.config["RECENT_TEMP_DIR"]

                msg = f"Recent scanner: starting scan (root={download_root}, temp={temp_root})"
                print(msg, flush=True)
                current_app.logger.warning(msg)

                recent_files = get_recent_files(download_root, limit=limit)
                msg = f"Recent scanner: get_recent_files returned {len(recent_files)} files"
                print(msg, flush=True)
                current_app.logger.warning(msg)

                if recent_files:
                    sync_temp_folder(recent_files, temp_root)
                else:
                    msg = "Recent scanner: no files found to sync."
                    print(msg, flush=True)
                    current_app.logger.warning(msg)

                msg = f"Recent scanner: cycle complete for root {download_root}"
                print(msg, flush=True)
                current_app.logger.warning(msg)

            except Exception as e:
                msg = f"Recent scanner failed: {e}"
                print(msg, flush=True)
                current_app.logger.exception(msg)

            interval_seconds = _get_interval_seconds()
            msg = f"Recent scanner: sleeping for {interval_seconds} seconds."
            print(msg, flush=True)
            current_app.logger.warning(msg)
            time.sleep(interval_seconds)


def start_recent_scanner(app):
    """
    Start the background thread once.
    """
    import threading

    if getattr(app, "_recent_scanner_started", False):
        # Extra debug
        msg = "Recent scanner: start_recent_scanner called but already started"
        print(msg, flush=True)
        app.logger.warning(msg)
        return

    app._recent_scanner_started = True

    msg = "Recent scanner: starting background thread"
    print(msg, flush=True)
    app.logger.warning(msg)

    t = threading.Thread(
        target=recent_scanner_loop,
        args=(app,),
        daemon=True,
    )
    t.start()
