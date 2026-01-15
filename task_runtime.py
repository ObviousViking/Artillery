import os
import shlex
import shutil
import subprocess
import threading
import time
import datetime as dt
import logging
import signal
from typing import Optional, Dict

import mediawall_runtime as mw

logger = logging.getLogger("artillery")

TASKS_ROOT = os.environ.get("TASKS_DIR") or "/tasks"
CONFIG_ROOT = os.environ.get("CONFIG_DIR") or "/config"
DOWNLOADS_ROOT = os.environ.get("DOWNLOADS_DIR") or "/downloads"

CONFIG_FILE = os.path.join(CONFIG_ROOT, "gallery-dl.conf")

# Track running processes for cancel/pause/resume.
RUNNING_PROCS: Dict[str, subprocess.Popen] = {}
RUNNING_PROCS_LOCK = threading.Lock()


def ensure_data_dirs(*, ensure_downloads: bool = False):
    os.makedirs(TASKS_ROOT, exist_ok=True)
    os.makedirs(CONFIG_ROOT, exist_ok=True)
    os.makedirs(mw.MEDIA_WALL_DIR, exist_ok=True)
    os.makedirs(mw.MEDIA_WALL_DIR_PREV, exist_ok=True)
    os.makedirs(mw.MEDIA_WALL_DIR_NEXT, exist_ok=True)
    if ensure_downloads:
        os.makedirs(DOWNLOADS_ROOT, exist_ok=True)


def read_text(path: str, *, strip: bool = True) -> Optional[str]:
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        data = f.read()
    if strip:
        data = data.strip()
    return data or None


def write_text(path: str, content: str):
    dirpath = os.path.dirname(path) or "."
    os.makedirs(dirpath, exist_ok=True)

    tmp_path = f"{path}.tmp.{os.getpid()}"
    try:
        with open(tmp_path, "w", encoding="utf-8", errors="replace") as f:
            f.write(content)
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception as exc:
                # fsync failures are non-fatal for our use case; log for diagnostics only.
                logger.debug("fsync failed for temporary file %s: %s", tmp_path, exc)
        os.replace(tmp_path, path)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception as exc:
            # Failure to remove the temporary file is non-fatal; log and continue.
            logger.debug("Failed to remove temporary file %s: %s", tmp_path, exc)


def _get_proc_for_task(slug: str) -> Optional[subprocess.Popen]:
    with RUNNING_PROCS_LOCK:
        proc = RUNNING_PROCS.get(slug)
        if proc and proc.poll() is None:
            return proc
    return None


def _get_pid_for_task(slug: str, task_folder: str) -> Optional[int]:
    proc = _get_proc_for_task(slug)
    if proc is not None:
        return proc.pid

    pid_path = os.path.join(task_folder, "pid")
    pid_text = read_text(pid_path)
    if not pid_text:
        return None
    try:
        return int(pid_text)
    except (TypeError, ValueError):
        return None


def signal_task(slug: str, task_folder: str, sig) -> bool:
    pid = _get_pid_for_task(slug, task_folder)
    if not pid:
        return False
    try:
        os.killpg(pid, sig)
        return True
    except ProcessLookupError:
        return False
    except Exception as exc:
        logger.warning("Failed sending signal %s to %s: %s", sig, slug, exc)
        return False


def cleanup_task_state(slug: str, task_folder: str):
    with RUNNING_PROCS_LOCK:
        RUNNING_PROCS.pop(slug, None)
    for name in ("pid", "lock"):
        p = os.path.join(task_folder, name)
        try:
            if os.path.exists(p):
                os.remove(p)
        except Exception as exc:
            logger.warning(
                "Failed to remove task state file %s for %s: %s",
                p,
                slug,
                exc,
            )


def clear_stale_lock(slug: str, task_folder: str):
    lock_path = os.path.join(task_folder, "lock")
    if not os.path.exists(lock_path):
        return
    pid = _get_pid_for_task(slug, task_folder)
    if not pid:
        cleanup_task_state(slug, task_folder)
        return
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        cleanup_task_state(slug, task_folder)


def kill_task(slug: str, task_folder: str) -> bool:
    proc = _get_proc_for_task(slug)
    pid = _get_pid_for_task(slug, task_folder)
    if not pid:
        cleanup_task_state(slug, task_folder)
        return False

    for sig, wait_s in ((signal.SIGINT, 1.5), (signal.SIGTERM, 1.5), (signal.SIGKILL, 0.5)):
        try:
            os.killpg(pid, sig)
        except ProcessLookupError:
            cleanup_task_state(slug, task_folder)
            return True
        except Exception as exc:
            logger.warning("Failed sending signal %s to %s: %s", sig, slug, exc)

        deadline = time.time() + wait_s
        while wait_s > 0 and time.time() < deadline:
            if proc and proc.poll() is not None:
                cleanup_task_state(slug, task_folder)
                return True
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                cleanup_task_state(slug, task_folder)
                return True
            time.sleep(0.1)

    return False


def _utcnow() -> str:
    return (
        dt.datetime.now(dt.timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "")
        + "Z"
    )


def run_task_background(
    task_folder: str,
    *,
    media_wall_enabled: bool = True,
    media_wall_cache_videos: bool = False,
    media_wall_copy_limit: int = 100,
    media_wall_auto_ingest: bool = True,
    media_wall_auto_refresh: bool = True,
):
    ensure_data_dirs(ensure_downloads=True)

    lock_path = os.path.join(task_folder, "lock")
    logs_path = os.path.join(task_folder, "logs.txt")
    last_run_path = os.path.join(task_folder, "last_run.txt")
    command_path = os.path.join(task_folder, "command.txt")
    urls_file = os.path.join(task_folder, "urls.txt")
    pid_path = os.path.join(task_folder, "pid")
    slug = os.path.basename(task_folder.rstrip("/"))

    logs_dir = os.path.join(task_folder, "logs")
    os.makedirs(logs_dir, exist_ok=True)

    command = read_text(command_path)
    if not command:
        with open(logs_path, "a", encoding="utf-8") as logf:
            logf.write("\nNo command configured for this task.\n")
        try:
            if os.path.exists(lock_path):
                os.remove(lock_path)
        except Exception:
            pass
        return

    if not os.path.exists(urls_file):
        with open(logs_path, "a", encoding="utf-8") as logf:
            logf.write("\nurls.txt not found for this task.\n")
        try:
            if os.path.exists(lock_path):
                os.remove(lock_path)
        except Exception:
            pass
        return

    now = _utcnow()
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_log_path = os.path.join(logs_dir, f"run_{timestamp}.log")

    try:
        cmd_parts = shlex.split(command)
    except ValueError as exc:
        with open(logs_path, "a", encoding="utf-8") as logf:
            logf.write(f"\nFailed to parse command: {exc}\n")
        try:
            if os.path.exists(lock_path):
                os.remove(lock_path)
        except Exception:
            pass
        return

    env = os.environ.copy()
    env["GALLERY_DL_CONFIG"] = CONFIG_FILE
    env["PATH"] = env.get("PATH", "") + os.pathsep + "/usr/local/bin"

    proc = None
    returncode = None

    try:
        config_exists = os.path.exists(CONFIG_FILE)
        header = f"\n\n==== Run at {now} ====\n"
        header += f"Artillery: using config {CONFIG_FILE} (exists={config_exists})\n"
        header += f"$ {' '.join(cmd_parts)}\n\n"

        with open(logs_path, "a", encoding="utf-8") as logf:
            logf.write(header)
            logf.flush()

        with open(run_log_path, "w", encoding="utf-8") as run_logf:
            run_logf.write(header)
            run_logf.flush()

            proc = subprocess.Popen(
                cmd_parts,
                cwd=task_folder,
                stdout=run_logf,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
                start_new_session=True,
            )

        if proc is not None:
            try:
                write_text(pid_path, str(proc.pid))
            except Exception as exc:
                logger.debug("Failed to write PID file %s for task %s: %s", pid_path, slug, exc)
            with RUNNING_PROCS_LOCK:
                RUNNING_PROCS[slug] = proc

        returncode = proc.wait() if proc is not None else -1
        write_text(last_run_path, now)

        if returncode == 0:
            footer = "\nTask finished successfully.\n"
        elif returncode is None:
            footer = "\nTask ended with unknown status.\n"
        else:
            footer = f"\nTask exited with code {returncode}.\n"

        with open(run_log_path, "a", encoding="utf-8") as run_logf:
            run_logf.write(footer)

        with open(logs_path, "a", encoding="utf-8") as logf:
            with open(run_log_path, "r", encoding="utf-8", errors="replace") as run_logf:
                for line in run_logf:
                    if line.startswith("$ "):
                        break
                shutil.copyfileobj(run_logf, logf)

    except Exception as exc:
        with open(logs_path, "a", encoding="utf-8") as logf:
            logf.write(f"\nERROR while running task: {exc}\n")
        try:
            with open(run_log_path, "a", encoding="utf-8") as run_logf:
                run_logf.write(f"\nERROR while running task: {exc}\n")
        except Exception as log_exc:
            logger.warning("Failed to write error details to run log %s: %s", run_log_path, log_exc)
    finally:
        with RUNNING_PROCS_LOCK:
            if proc is not None and RUNNING_PROCS.get(slug) is proc:
                RUNNING_PROCS.pop(slug, None)

        try:
            if os.path.exists(pid_path):
                os.remove(pid_path)
        except Exception:
            pass

        if media_wall_enabled and media_wall_auto_ingest:
            try:
                conn = mw.open_db(mw.MEDIA_DB)
                mw.ingest_task_log(conn, slug, logs_path, downloads_root=DOWNLOADS_ROOT, full_rescan=False)

                if media_wall_auto_refresh and mw.should_refresh_cache(conn):
                    mw.refresh_wall_cache(
                        conn,
                        min(int(media_wall_copy_limit), 100),
                        downloads_root=DOWNLOADS_ROOT,
                        cache_videos=media_wall_cache_videos,
                    )

                conn.close()
            except Exception as exc:
                logger.warning("Media wall update failed: %s", exc)

        try:
            if os.path.exists(lock_path):
                os.remove(lock_path)
        except Exception as exc:
            logger.warning("Failed to remove lock file %s: %s", lock_path, exc)
