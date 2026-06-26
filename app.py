import os
import io
import json
import zipfile
import mimetypes
import datetime as dt
import re
import urllib.request
import subprocess
import shlex
import shutil
import threading
import time
import logging
import signal
import faulthandler
import hashlib
import random
import secrets
import atexit
from pathlib import Path
from typing import Optional, List, Tuple
from croniter import croniter
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# Ensure webp is served as image/webp on systems with incomplete MIME databases
mimetypes.add_type('image/webp', '.webp')

from flask import (
    Flask, render_template, request,
    redirect, url_for, flash, send_from_directory, Response,
    send_file, jsonify,
)
from flask_wtf.csrf import CSRFProtect

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", secrets.token_hex(32))

csrf = CSRFProtect(app)

# ---------------------------------------------------------------------
# Logging / Debug toggles
# ---------------------------------------------------------------------

LOG_LEVEL = os.environ.get("ARTILLERY_LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))
app.logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

DEBUG_REQUEST_TIMING = os.environ.get("ARTILLERY_DEBUG_REQUESTS", "0") == "1"
DEBUG_FS_TIMING = os.environ.get("ARTILLERY_DEBUG_FS", "0") == "1"

HANG_DUMP_SECONDS = int(os.environ.get("ARTILLERY_HANG_DUMP_SECONDS", "0") or "0")

faulthandler.enable()
try:
    faulthandler.register(signal.SIGUSR1, all_threads=True)
except Exception:
    app.logger.debug("SIGUSR1 not available on this platform — faulthandler signal handler skipped")

if HANG_DUMP_SECONDS > 0:
    faulthandler.dump_traceback_later(HANG_DUMP_SECONDS, repeat=True)

# ---------------------------------------------------------------------
# Base data directories
# ---------------------------------------------------------------------

TASKS_ROOT = os.environ.get("TASKS_DIR") or "/tasks"
CONFIG_ROOT = os.environ.get("CONFIG_DIR") or "/config"
DOWNLOADS_ROOT = os.environ.get("DOWNLOADS_DIR") or "/downloads"

CONFIG_FILE  = os.path.join(CONFIG_ROOT, "gallery-dl.conf")
KIOSKS_ROOT  = os.path.join(CONFIG_ROOT, "kiosks")

DEFAULT_CONFIG_URL = os.environ.get(
    "GALLERYDL_DEFAULT_CONFIG_URL",
    "https://raw.githubusercontent.com/mikf/gallery-dl/master/docs/gallery-dl.conf",
)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
VIDEO_EXTS = {".mp4", ".webm", ".mkv"}
MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS

TASK_TIMEOUT_SECONDS = int(os.environ.get("TASK_TIMEOUT_SECONDS", "0") or "0")
MAX_ROTATED_LOGS = 5

def _get_task_timeout(task_folder: str) -> Optional[int]:
    txt = read_text(os.path.join(task_folder, "timeout.txt"))
    if txt and txt.strip().isdigit():
        v = int(txt.strip())
        return v if v > 0 else None
    return TASK_TIMEOUT_SECONDS if TASK_TIMEOUT_SECONDS > 0 else None

def _rotate_logs(task_folder: str) -> None:
    logs_path = os.path.join(task_folder, "logs.txt")
    if not os.path.exists(logs_path) or os.path.getsize(logs_path) == 0:
        return
    stamp = dt.datetime.utcnow().strftime("%Y-%m-%dT%H%M%S")
    archived = os.path.join(task_folder, f"logs-{stamp}.txt")
    try:
        os.rename(logs_path, archived)
    except Exception:
        app.logger.warning("Could not rotate log for %s", task_folder, exc_info=True)
        return
    pat = re.compile(r'^logs-\d{4}-\d{2}-\d{2}T\d{6}\.txt$')
    archives = sorted(f for f in os.listdir(task_folder) if pat.match(f))
    for old in archives[:-MAX_ROTATED_LOGS]:
        try:
            os.remove(os.path.join(task_folder, old))
        except Exception:
            app.logger.warning("Could not remove old log archive %s", old, exc_info=True)

def _write_last_error(task_folder: str, message: str) -> None:
    try:
        Path(os.path.join(task_folder, "last_error.txt")).write_text(
            message.strip(), encoding="utf-8"
        )
    except Exception:
        app.logger.warning("Could not write last_error.txt for %s", task_folder, exc_info=True)

def _clear_last_error(task_folder: str) -> None:
    p = os.path.join(task_folder, "last_error.txt")
    try:
        if os.path.exists(p):
            os.remove(p)
    except Exception:
        app.logger.warning("Could not clear last_error.txt for %s", task_folder, exc_info=True)

def _record_run(task_folder: str, success: bool, duration: float, stopped: bool) -> None:
    history_path = os.path.join(task_folder, "run_history.jsonl")
    entry = json.dumps({
        "ts": dt.datetime.utcnow().isoformat() + "Z",
        "success": success,
        "duration": round(duration, 1),
        "stopped": stopped,
    })
    try:
        with _HISTORY_LOCK:
            with open(history_path, "a", encoding="utf-8") as f:
                f.write(entry + "\n")
            with open(history_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if len(lines) > 100:
                with open(history_path, "w", encoding="utf-8") as f:
                    f.writelines(lines[-100:])
    except Exception:
        app.logger.exception("Could not write run history for %s", task_folder)

# ---------------------------------------------------------------------
# Media wall (DB + cache folder)
# ---------------------------------------------------------------------

MEDIA_WALL_DIR = os.path.join(CONFIG_ROOT, "media_wall")
MEDIA_WALL_SCAN_CRON_FILE = os.path.join(CONFIG_ROOT, "mediawall_scan_cron.txt")
MEDIA_WALL_ENABLED_FILE = os.path.join(CONFIG_ROOT, "mediawall_enabled.txt")

MEDIA_WALL_REFRESH_LOCK = threading.Lock()
_HISTORY_LOCK          = threading.Lock()  # serialises concurrent run_history.jsonl writes

# Disable aggressive caching of send_from_directory responses
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0


# Media wall constants
MEDIA_WALL_ROWS = 3
MEDIA_WALL_ENABLED_DEFAULT = os.environ.get("MEDIA_WALL_ENABLED", "1") == "1"
MEDIA_WALL_ITEMS_ON_PAGE = int(os.environ.get("MEDIA_WALL_ITEMS", "45"))
MEDIA_WALL_CACHE_VIDEOS = os.environ.get("MEDIA_WALL_CACHE_VIDEOS", "0") == "1"
MEDIA_WALL_COPY_LIMIT = int(os.environ.get("MEDIA_WALL_COPY_LIMIT", "100"))
MEDIA_WALL_AUTO_INGEST_ON_TASK_END = os.environ.get("MEDIA_WALL_AUTO_INGEST_ON_TASK_END", "1") == "1"
MEDIA_WALL_AUTO_REFRESH_ON_TASK_END = os.environ.get("MEDIA_WALL_AUTO_REFRESH_ON_TASK_END", "1") == "1"
MEDIA_WALL_MIN_REFRESH_SECONDS = int(os.environ.get("MEDIA_WALL_MIN_REFRESH_SECONDS", "300"))
MEDIA_WALL_SSE_ENABLED = os.environ.get("MEDIA_WALL_SSE", "0") == "1"
MEDIA_WALL_SCAN_CRON_DEFAULT = os.environ.get("MEDIA_WALL_SCAN_CRON", "*/1 * * * *")
MEDIA_WALL_POLL_INTERVAL = int(os.environ.get("MEDIA_WALL_POLL_INTERVAL", "60"))
MEDIA_WALL_LOG_TAIL_LINES = int(os.environ.get("MEDIA_WALL_LOG_TAIL_LINES", "2000"))
RECENT_DOWNLOADS_PER_TASK = int(os.environ.get("RECENT_DOWNLOADS_PER_TASK", "20"))
RECENT_LOG_TAIL_LINES = int(os.environ.get("RECENT_LOG_TAIL_LINES", "200"))
ONE_TIME_LOG_FILE = os.path.join(CONFIG_ROOT, "one_time_download.log")
ONE_TIME_PID_FILE = os.path.join(CONFIG_ROOT, "one_time_download.pid")
ONE_TIME_STOP_FILE = os.path.join(CONFIG_ROOT, "one_time_download.stop")
ONE_TIME_LOG_TAIL_LINES = int(os.environ.get("ONE_TIME_LOG_TAIL_LINES", "50"))
ONE_TIME_RECENT_DOWNLOADS = int(os.environ.get("ONE_TIME_RECENT_DOWNLOADS", "16"))

# Media wall notify file for SSE
MEDIAWALL_NOTIFY_FILE = os.path.join(os.environ.get('CONFIG_DIR', '/config'), 'mediawall.notify')

def touch_mediawall_notify():
    try:
        os.makedirs(os.path.dirname(MEDIAWALL_NOTIFY_FILE), exist_ok=True)
        with open(MEDIAWALL_NOTIFY_FILE, 'a'):
            os.utime(MEDIAWALL_NOTIFY_FILE, None)
    except Exception:
        app.logger.debug("Could not touch mediawall notify file", exc_info=True)

# ---------------------------------------------------------------------
# Optional request timing
# ---------------------------------------------------------------------

if DEBUG_REQUEST_TIMING:
    @app.before_request
    def _t_start():
        request._t0 = time.perf_counter()

    @app.after_request
    def _t_end(resp):
        t0 = getattr(request, "_t0", None)
        if t0 is not None:
            dt_ms = (time.perf_counter() - t0) * 1000
            app.logger.info("REQ %s %s -> %s (%.1fms)",
                            request.method, request.path, resp.status_code, dt_ms)
        return resp

# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def _utcnow() -> str:
    return dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"


def slugify(name: str) -> str:
    name = name.strip().lower()
    name = re.sub(r"\s+", "-", name)
    name = re.sub(r"[^a-z0-9-]+", "", name)
    return name or "task"


def ensure_data_dirs(ensure_downloads: bool = False):
    """
    Ensure base directories exist.

    CRITICAL: do not touch /downloads unless explicitly requested.
    """
    t0 = time.perf_counter() if DEBUG_FS_TIMING else None

    os.makedirs(TASKS_ROOT, exist_ok=True)
    os.makedirs(CONFIG_ROOT, exist_ok=True)
    os.makedirs(MEDIA_WALL_DIR, exist_ok=True)


    if ensure_downloads:
        os.makedirs(DOWNLOADS_ROOT, exist_ok=True)

    if DEBUG_FS_TIMING and t0 is not None:
        ms = (time.perf_counter() - t0) * 1000
        app.logger.info("ensure_data_dirs(downloads=%s) %.1fms", ensure_downloads, ms)


def read_text(path: str):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read().strip() or None


def write_text(path: str, content: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _is_process_running(pid: int) -> bool:
    try:
        if pid <= 0:
            return False
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _get_one_time_status() -> dict:
    running = False
    pid = None
    if os.path.exists(ONE_TIME_PID_FILE):
        pid_text = read_text(ONE_TIME_PID_FILE)
        if pid_text:
            try:
                pid = int(pid_text.strip())
            except ValueError:
                pid = None
        if pid and _is_process_running(pid):
            running = True
        else:
            try:
                os.remove(ONE_TIME_PID_FILE)
            except Exception:
                app.logger.debug("Could not remove stale one-time PID file")
    return {"running": running, "pid": pid}


def _get_media_wall_enabled() -> bool:
    raw = read_text(MEDIA_WALL_ENABLED_FILE)
    if raw is None:
        return MEDIA_WALL_ENABLED_DEFAULT
    return raw.strip() in ("1", "true", "True", "yes", "on")

def _set_media_wall_enabled(value: bool) -> None:
    write_text(MEDIA_WALL_ENABLED_FILE, "1" if value else "0")

def _get_media_wall_scan_cron() -> str:
    raw = read_text(MEDIA_WALL_SCAN_CRON_FILE)
    expr = (raw or MEDIA_WALL_SCAN_CRON_DEFAULT).strip()
    return expr if croniter.is_valid(expr) else MEDIA_WALL_SCAN_CRON_DEFAULT

def _set_media_wall_scan_cron(expr: str) -> None:
    write_text(MEDIA_WALL_SCAN_CRON_FILE, expr.strip())

# In-memory cache to reduce repeated disk reads on /tasks
_TASK_CACHE = {}

# Coarse TTL cache for the full task list — short-circuits per-task stat sweeps
# when nothing has changed between requests (e.g. during the 5 s polling loop).
_TASK_LIST_CACHE: dict = {"ts": 0.0, "tasks": None}
_TASK_LIST_TTL = 2.0  # seconds

def _invalidate_task_cache() -> None:
    _TASK_LIST_CACHE["ts"] = 0.0
    _TASK_LIST_CACHE["tasks"] = None

# Slug validation — block path traversal attempts on every <slug> route.
_SLUG_RE = re.compile(r'^[a-z0-9][a-z0-9-]*$')

def is_valid_slug(slug: str) -> bool:
    return bool(_SLUG_RE.match(slug))

# ── APScheduler ────────────────────────────────────────────────────────────────
_bg_scheduler = BackgroundScheduler(daemon=True)

def _make_cron_trigger(cron_expr: str):
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        return None
    minute, hour, day, month, day_of_week = parts
    try:
        return CronTrigger(
            minute=minute, hour=hour, day=day,
            month=month, day_of_week=day_of_week,
        )
    except Exception:
        return None

def _run_scheduled_task(slug: str) -> None:
    task_folder = os.path.join(TASKS_ROOT, slug)
    if not os.path.isdir(task_folder):
        return
    if os.path.exists(os.path.join(task_folder, "paused")):
        return
    lock_path = os.path.join(task_folder, "lock")
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError:
        return
    threading.Thread(target=run_task_background, args=(task_folder,), daemon=True).start()

def _reschedule_task(slug: str, cron_expr: str) -> None:
    trigger = _make_cron_trigger(cron_expr)
    if trigger is None:
        _unschedule_task(slug)
        return
    _bg_scheduler.add_job(
        _run_scheduled_task,
        trigger=trigger,
        id=f"task_{slug}",
        replace_existing=True,
        args=[slug],
    )

def _unschedule_task(slug: str) -> None:
    try:
        _bg_scheduler.remove_job(f"task_{slug}")
    except Exception:
        app.logger.debug("Scheduler job task_%s not found (already removed or never added)", slug)

def _load_all_schedules() -> None:
    if not os.path.isdir(TASKS_ROOT):
        return
    for entry in os.listdir(TASKS_ROOT):
        task_path = os.path.join(TASKS_ROOT, entry)
        if not os.path.isdir(task_path):
            continue
        cron_expr = read_text(os.path.join(task_path, "cron.txt"))
        if cron_expr and cron_expr.strip():
            _reschedule_task(entry, cron_expr.strip())

def _task_mtimes(task_path: str) -> dict:
    def _mt(p):
        try:
            return os.path.getmtime(p)
        except Exception:
            return None
    return {
        "name": _mt(os.path.join(task_path, "name.txt")),
        "cron": _mt(os.path.join(task_path, "cron.txt")),
        "command": _mt(os.path.join(task_path, "command.txt")),
        "last_run": _mt(os.path.join(task_path, "last_run.txt")),
        "urls": _mt(os.path.join(task_path, "urls.txt")),
        "lock": _mt(os.path.join(task_path, "lock")),
        "paused": _mt(os.path.join(task_path, "paused")),
        "error": _mt(os.path.join(task_path, "error")),
        "archive":    _mt(os.path.join(task_path, "archive.sqlite")),
        "cookies":    _mt(os.path.join(task_path, "cookies.txt")),
        "last_error": _mt(os.path.join(task_path, "last_error.txt")),
        "timeout":    _mt(os.path.join(task_path, "timeout.txt")),
    }

def _cache_name_for_relpath(relpath: str) -> str:
    ext = os.path.splitext(relpath)[1].lower()
    h = hashlib.sha1(relpath.encode("utf-8", errors="ignore")).hexdigest()
    return f"{h}{ext}"

def _extract_relpath_from_log_line(line: str, downloads_root: str) -> Optional[str]:
    s = line.strip()
    if not s:
        return None

    s = s.replace("\\", "/")
    dr = downloads_root.replace("\\", "/").rstrip("/")
    dr_short = dr.lstrip("/")

    # Prefer full-line match to handle spaces in folders
    media_pattern = r"(?:jpg|jpeg|png|gif|webp|mp4|webm|mkv)"
    full_match = re.search(re.escape(dr) + r"/[^\r\n]*?\." + media_pattern, s, re.IGNORECASE)
    if full_match:
        cand = full_match.group(0)
        rel = cand[len(dr):].lstrip("/")
        if rel:
            return rel

    candidates = [tok for tok in re.split(r"\s+", s) if tok.startswith(dr)]
    if not candidates and dr in s:
        idx = s.find(dr)
        if idx != -1:
            cand = s[idx:].strip(" ,;\"'()[]")
            candidates = [cand]

    for cand in candidates:
        if cand == dr or cand.startswith(dr + "/"):
            rel = cand[len(dr):].lstrip("/")
            if not rel:
                continue
            ext = os.path.splitext(rel)[1].lower()
            if ext and ext in MEDIA_EXTS:
                return rel
        if cand.startswith(dr_short + "/"):
            rel = cand[len(dr_short):].lstrip("/")
            if not rel:
                continue
            ext = os.path.splitext(rel)[1].lower()
            if ext and ext in MEDIA_EXTS:
                return rel

    # Fallback: search for any media path containing downloads/ without a leading slash
    media_match = re.search(r"(?:^|\s)([^\s\"']+\.(?:jpg|jpeg|png|gif|webp|mp4|webm|mkv))(?:$|\s)", s, re.IGNORECASE)
    if media_match:
        cand = media_match.group(1)
        cand = cand.strip(" ,;\"'()[]")
        cand = cand.replace("\\", "/")
        if dr in cand:
            rel = cand.split(dr, 1)[-1].lstrip("/")
            if rel:
                return rel
        if ("/" + dr_short + "/") in cand or cand.startswith(dr_short + "/"):
            rel = cand.split(dr_short + "/", 1)[-1].lstrip("/")
            if rel:
                return rel

    return None

def _count_file_lines(path: str) -> int:
    """Count lines in a file by streaming in chunks — safe for very large files."""
    try:
        count = 0
        with open(path, 'rb') as f:
            while True:
                block = f.read(65536)
                if not block:
                    break
                count += block.count(b'\n')
        return count
    except Exception:
        return 0


def _tail_lines(path: str, max_lines: int = 500, chunk_size: int = 8192) -> List[str]:
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            end = f.tell()
            buffer = bytearray()
            lines = 0
            pos = end
            while pos > 0 and lines <= max_lines:
                read_size = chunk_size if pos >= chunk_size else pos
                pos -= read_size
                f.seek(pos)
                chunk = f.read(read_size)
                buffer[:0] = chunk
                lines = buffer.count(b"\n")
            text = buffer.decode("utf-8", errors="ignore")
            return text.splitlines()[-max_lines:]
    except Exception:
        return []

def _recent_downloads_from_log(log_path: str, limit: int) -> List[dict]:
    if not os.path.exists(log_path):
        return []

    lines = _tail_lines(log_path, max_lines=RECENT_LOG_TAIL_LINES)
    items = []
    seen = set()

    for line in reversed(lines):
        rel = _extract_relpath_from_log_line(line, DOWNLOADS_ROOT)
        if not rel:
            continue
        if rel in seen:
            continue

        abs_path = os.path.join(DOWNLOADS_ROOT, rel)
        if not os.path.isfile(abs_path):
            continue

        ext = os.path.splitext(rel)[1].lower()
        items.append({
            "rel": rel,
            "ext": ext,
            "filename": os.path.basename(rel),
        })
        seen.add(rel)

        if len(items) >= limit:
            break

    return items

def _clean_dir(path: str):
    os.makedirs(path, exist_ok=True)
    for fn in os.listdir(path):
        try:
            os.remove(os.path.join(path, fn))
        except Exception:
            app.logger.warning("Could not remove media wall cache file %s", fn, exc_info=True)

def _refresh_media_wall_cache_from_downloads() -> dict:
    ensure_data_dirs(ensure_downloads=True)

    allowed = set(IMAGE_EXTS)
    if MEDIA_WALL_CACHE_VIDEOS:
        allowed |= set(VIDEO_EXTS)

    if not MEDIA_WALL_REFRESH_LOCK.acquire(blocking=False):
        app.logger.info("mediawall: refresh skipped (lock busy)")
        return {"picked": 0, "copied": 0, "skipped": 1}

    try:
        app.logger.info("mediawall: refresh started (cache_videos=%s, copy_limit=%s)", MEDIA_WALL_CACHE_VIDEOS, MEDIA_WALL_COPY_LIMIT)
        items = set()

        tasks_seen = 0
        if os.path.isdir(TASKS_ROOT):
            for slug in sorted(os.listdir(TASKS_ROOT)):
                task_dir = os.path.join(TASKS_ROOT, slug)
                if not os.path.isdir(task_dir):
                    continue
                log_path = os.path.join(task_dir, "logs.txt")
                if not os.path.exists(log_path):
                    continue
                tasks_seen += 1
                try:
                    for line in _tail_lines(log_path, max_lines=MEDIA_WALL_LOG_TAIL_LINES):
                        rel = _extract_relpath_from_log_line(line, DOWNLOADS_ROOT)
                        if not rel:
                            continue
                        ext = os.path.splitext(rel)[1].lower()
                        if ext in allowed:
                            src = os.path.join(DOWNLOADS_ROOT, rel)
                            if os.path.isfile(src):
                                items.add(rel)
                except Exception:
                    continue
        app.logger.info("mediawall: scanned logs (tasks=%s, items=%s)", tasks_seen, len(items))

        if not items:
            app.logger.info("mediawall: no log items found, scanning downloads...")
            for root, _dirs, files in os.walk(DOWNLOADS_ROOT):
                for fn in files:
                    ext = os.path.splitext(fn)[1].lower()
                    if ext not in allowed:
                        continue
                    path = os.path.join(root, fn)
                    rel = os.path.relpath(path, DOWNLOADS_ROOT)
                    if os.path.isfile(path):
                        items.add(rel)

        if not items:
            app.logger.info("mediawall: refresh found 0 items")
            return {"picked": 0, "copied": 0}

        items_list = list(items)
        pick_count = min(MEDIA_WALL_COPY_LIMIT, len(items_list))
        picked = random.sample(items_list, k=pick_count)

        _clean_dir(MEDIA_WALL_DIR)

        copied = 0
        failed = 0
        for rel in picked:
            src = os.path.join(DOWNLOADS_ROOT, rel)
            dst = os.path.join(MEDIA_WALL_DIR, _cache_name_for_relpath(rel))
            tmp = dst + ".tmp"
            try:
                if not os.path.isfile(src):
                    failed += 1
                    continue
                shutil.copy2(src, tmp)
                os.replace(tmp, dst)
                copied += 1
            except Exception:
                failed += 1
                app.logger.warning("Could not copy media wall file %s", rel, exc_info=True)
                try:
                    if os.path.exists(tmp):
                        os.remove(tmp)
                except Exception:
                    app.logger.debug("Could not remove tmp file %s", tmp)

        app.logger.info("mediawall: refresh completed (picked=%s, copied=%s, failed=%s)", len(picked), copied, failed)
        return {"picked": len(picked), "copied": copied, "failed": failed}
    finally:
        MEDIA_WALL_REFRESH_LOCK.release()

_MEDIA_WALL_SCAN_THREAD_STARTED = False

def _media_wall_scan_worker():
    last_minute = None
    last_expr = None
    next_run = None
    last_status_minute = None

    # one-time warmup if enabled and cache empty
    app.logger.info("mediawall: scan worker started (enabled=%s)", MEDIA_WALL_ENABLED)

    if MEDIA_WALL_ENABLED and not os.listdir(MEDIA_WALL_DIR):
        app.logger.info("mediawall: warmup refresh (cache empty)")
        _refresh_media_wall_cache_from_downloads()
        touch_mediawall_notify()

    while True:
        if not MEDIA_WALL_ENABLED:
            time.sleep(2)
            continue

        expr = _get_media_wall_scan_cron()
        now = dt.datetime.now()
        now_minute = now.replace(second=0, microsecond=0)
        minute_key = now_minute.strftime("%Y-%m-%d %H:%M")

        if expr != last_expr:
            last_expr = expr
            try:
                next_run = croniter(expr, now_minute).get_next(dt.datetime)
                app.logger.info("mediawall: schedule updated expr='%s', next_run=%s", expr, next_run)
            except Exception:
                app.logger.warning("mediawall: invalid cron expr '%s'", expr)
                next_run = None

        if next_run and now_minute >= next_run and minute_key != last_minute:
            last_minute = minute_key
            app.logger.info("mediawall: trigger refresh at %s (expr='%s')", now_minute, expr)
            _refresh_media_wall_cache_from_downloads()
            touch_mediawall_notify()
            try:
                next_run = croniter(expr, now_minute).get_next(dt.datetime)
                app.logger.info("mediawall: next_run=%s", next_run)
            except Exception:
                app.logger.warning("mediawall: failed to compute next run for expr '%s'", expr)
                next_run = None
        elif minute_key != last_status_minute:
            last_status_minute = minute_key
            app.logger.info("mediawall: waiting (now=%s, next_run=%s, expr='%s')", now_minute, next_run, expr)

        time.sleep(5)

def _start_media_wall_scan_thread():
    global _MEDIA_WALL_SCAN_THREAD_STARTED
    if _MEDIA_WALL_SCAN_THREAD_STARTED:
        return
    _MEDIA_WALL_SCAN_THREAD_STARTED = True
    threading.Thread(target=_media_wall_scan_worker, daemon=True).start()

# Initialize persisted media wall state
MEDIA_WALL_ENABLED = _get_media_wall_enabled()
_start_media_wall_scan_thread()

def load_tasks():
    now = time.time()
    if _TASK_LIST_CACHE["tasks"] is not None and now - _TASK_LIST_CACHE["ts"] < _TASK_LIST_TTL:
        return list(_TASK_LIST_CACHE["tasks"])

    ensure_data_dirs(ensure_downloads=False)

    tasks = []
    if not os.path.isdir(TASKS_ROOT):
        return tasks

    for entry in sorted(os.listdir(TASKS_ROOT)):
        task_path = os.path.join(TASKS_ROOT, entry)
        if not os.path.isdir(task_path):
            continue

        slug = entry
        mtimes = _task_mtimes(task_path)
        cached = _TASK_CACHE.get(slug)
        if cached and cached.get("_mtimes") == mtimes:
            tasks.append(cached["task"])
            continue

        name = read_text(os.path.join(task_path, "name.txt")) or slug
        schedule = read_text(os.path.join(task_path, "cron.txt"))
        command = read_text(os.path.join(task_path, "command.txt")) or "gallery-dl --input-file urls.txt"
        last_run = read_text(os.path.join(task_path, "last_run.txt"))
        url_count   = _count_file_lines(os.path.join(task_path, "urls.txt"))
        has_archive = os.path.exists(os.path.join(task_path, "archive.sqlite"))
        has_cookies = os.path.exists(os.path.join(task_path, "cookies.txt"))

        lock_path   = os.path.join(task_path, "lock")
        paused_path = os.path.join(task_path, "paused")
        error_path  = os.path.join(task_path, "error")

        if os.path.exists(lock_path):
            status = "running"
        elif os.path.exists(paused_path):
            status = "paused"
        elif os.path.exists(error_path):
            status = "error"
        else:
            status = "idle"

        next_run = None
        if schedule and croniter.is_valid(schedule):
            try:
                next_run = croniter(schedule, dt.datetime.now()).get_next(dt.datetime).isoformat(timespec="seconds")
            except Exception:
                app.logger.warning("Could not calculate next_run for cron '%s'", schedule, exc_info=True)

        last_error = ""
        if status == "error":
            last_error = read_text(os.path.join(task_path, "last_error.txt")) or ""

        timeout_val = read_text(os.path.join(task_path, "timeout.txt")) or ""

        task = {
            "id": slug,
            "name": name,
            "slug": slug,
            "schedule": schedule,
            "next_run": next_run,
            "status": status,
            "last_run": last_run,
            "task_path": task_path,
            "urls_file": "urls.txt",
            "command": command,
            "url_count": url_count,
            "has_archive": has_archive,
            "has_cookies": has_cookies,
            "last_error": last_error,
            "timeout": timeout_val.strip(),
        }
        _TASK_CACHE[slug] = {"_mtimes": mtimes, "task": task}
        tasks.append(task)

    _TASK_LIST_CACHE["ts"] = time.time()
    _TASK_LIST_CACHE["tasks"] = tasks
    return tasks

# ---------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------

# ── Kiosk helpers ────────────────────────────────────────────────────────────

def _kiosk_settings(kslug: str) -> dict:
    raw = read_text(os.path.join(KIOSKS_ROOT, kslug, "settings.json"))
    try:
        return json.loads(raw) if raw else {}
    except Exception:
        app.logger.warning("Could not parse kiosk settings for %s", kslug)
        return {}

def _save_kiosk_settings(kslug: str, settings: dict) -> None:
    p = os.path.join(KIOSKS_ROOT, kslug, "settings.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    write_text(p, json.dumps(settings, indent=2))

def _list_kiosks() -> list:
    result = []
    if not os.path.isdir(KIOSKS_ROOT):
        return result
    for kslug in sorted(os.listdir(KIOSKS_ROOT)):
        kdir = os.path.join(KIOSKS_ROOT, kslug)
        if not os.path.isdir(kdir):
            continue
        settings = _kiosk_settings(kslug)
        idir = os.path.join(kdir, "images")
        count = sum(1 for f in os.listdir(idir) if os.path.isfile(os.path.join(idir, f))) if os.path.isdir(idir) else 0
        result.append({
            "slug": kslug,
            "name": settings.get("name", kslug),
            "interval": settings.get("interval", 10),
            "order": settings.get("order", "random"),
            "image_count": count,
        })
    return result

# ---------------------------------------------------------------------

@app.route("/healthz")
def healthz():
    return Response("ok\n", mimetype="text/plain")

# ---------------------------------------------------------------------
# Media wall admin endpoints
# ---------------------------------------------------------------------

@app.route("/mediawall/toggle", methods=["POST"])
def mediawall_toggle():
    """Toggle media wall enabled/disabled."""
    global MEDIA_WALL_ENABLED
    with MEDIA_WALL_REFRESH_LOCK:
        MEDIA_WALL_ENABLED = not MEDIA_WALL_ENABLED
        new_value = MEDIA_WALL_ENABLED
    _set_media_wall_enabled(new_value)
    if new_value:
        _start_media_wall_scan_thread()
    status = "enabled" if new_value else "disabled"
    os.environ["MEDIA_WALL_ENABLED"] = "1" if new_value else "0"
    flash(f"Media wall {status}", "success")
    return redirect(url_for("config_page"))

@app.route("/mediawall/refresh", methods=["POST"])
def mediawall_refresh():
    if not MEDIA_WALL_ENABLED:
        flash("Media wall is disabled.", "error")
        return redirect(url_for("config_page"))
    def _run_refresh():
        result = _refresh_media_wall_cache_from_downloads()
        touch_mediawall_notify()
        app.logger.info(
            "mediawall: manual refresh done (picked=%s, copied=%s, failed=%s, skipped=%s)",
            result.get("picked", 0),
            result.get("copied", 0),
            result.get("failed", 0),
            result.get("skipped", 0),
        )

    threading.Thread(target=_run_refresh, daemon=True).start()
    flash("Media wall refresh started.", "success")
    return redirect(url_for("config_page"))

# ---------------------------------------------------------------------
# Cached wall file route (fast: served from /config/media_wall)
# ---------------------------------------------------------------------

@app.route("/wall/<path:filename>")
def wall_file(filename):
    ensure_data_dirs(ensure_downloads=False)
    return send_from_directory(MEDIA_WALL_DIR, filename, conditional=True)

@app.route('/mediawall/api/list_cache')
def mediawall_list_cache():
    """
    Return JSON: { items: [{ name, url, mtime }, ...] }
    Reads files from CONFIG_DIR/media_wall
    """
    config_dir = os.environ.get('CONFIG_DIR', '/config')
    media_dir = os.path.join(config_dir, 'media_wall')
    items = []
    try:
        allowed_img_ext = {'jpg','jpeg','png','gif','webp'}
        allowed_vid_ext = {'mp4','webm','mkv'}
        cache_videos = os.environ.get('MEDIA_WALL_CACHE_VIDEOS', '0') in ('1','true','True')
        if os.path.isdir(media_dir):
            for fname in sorted(os.listdir(media_dir), reverse=True):
                fpath = os.path.join(media_dir, fname)
                if not os.path.isfile(fpath):
                    continue
                ext = (fname.rsplit('.',1)[-1] or "").lower()
                if ext in allowed_img_ext or (cache_videos and ext in allowed_vid_ext):
                    try:
                        mtime = int(os.path.getmtime(fpath))
                    except Exception:
                        mtime = 0
                    try:
                        file_url = url_for('wall_file', filename=fname)
                    except Exception:
                        file_url = '/wall/' + fname
                    items.append({'name': fname, 'url': file_url, 'mtime': mtime})
    except Exception:
        app.logger.exception("Error listing media wall cache directory")
    return jsonify({'items': items})

@app.route("/mediawall/events")
def mediawall_events():
    """SSE endpoint that emits mediawall_update when notify file mtime changes."""
    if not MEDIA_WALL_SSE_ENABLED:
        return Response("", status=204)
    def gen():
        last_mtime = 0
        try:
            while True:
                try:
                    if os.path.exists(MEDIAWALL_NOTIFY_FILE):
                        m = os.path.getmtime(MEDIAWALL_NOTIFY_FILE)
                        if m != last_mtime:
                            last_mtime = m
                            yield f'event: mediawall_update\ndata: {int(m)}\n\n'
                    time.sleep(1)
                except Exception:
                    time.sleep(1)
        except GeneratorExit:
            return
    return Response(gen(), mimetype='text/event-stream')

# ---------------------------------------------------------------------
# Home page (uses cache folder; never scans /downloads)
# ---------------------------------------------------------------------

@app.route("/")
def home():
    tasks = load_tasks()

    urls = []
    has_media = False
    recent_rows = [[] for _ in range(MEDIA_WALL_ROWS)]

    if MEDIA_WALL_ENABLED:
        os.makedirs(MEDIA_WALL_DIR, exist_ok=True)
        cached_files = [
            fn for fn in os.listdir(MEDIA_WALL_DIR)
            if os.path.splitext(fn)[1].lower() in MEDIA_EXTS and not fn.endswith(".tmp")
        ]
        cached_files = cached_files[:MEDIA_WALL_ITEMS_ON_PAGE]

        urls = [url_for("wall_file", filename=fn) for fn in cached_files]
        has_media = len(urls) > 0

        for i, u in enumerate(urls):
            recent_rows[i % MEDIA_WALL_ROWS].append(u)

    return render_template(
        "home.html",
        tasks_count=len(tasks),
        recent_rows=recent_rows,
        has_media=has_media,
        media_wall_enabled=MEDIA_WALL_ENABLED,
        media_wall_scan_cron=_get_media_wall_scan_cron(),
        media_wall_poll_interval=MEDIA_WALL_POLL_INTERVAL,
        media_wall_sse_enabled=MEDIA_WALL_SSE_ENABLED,
    )

# ---------------------------------------------------------------------
# Recent downloads (per task, based on logs)
# ---------------------------------------------------------------------

@app.route("/recent")
def recent_downloads():
    ensure_data_dirs(ensure_downloads=False)
    tasks = load_tasks()

    task_items = []
    for task in tasks:
        log_path = os.path.join(TASKS_ROOT, task["slug"], "logs.txt")
        items = _recent_downloads_from_log(log_path, RECENT_DOWNLOADS_PER_TASK)
        for item in items:
            item["url"] = url_for("media_file", subpath=item["rel"])
            item["is_image"] = item["ext"] in IMAGE_EXTS
            item["is_video"] = item["ext"] in VIDEO_EXTS
        task_items.append({
            "name": task["name"],
            "slug": task["slug"],
            "recent_items": items,
        })

    return render_template(
        "recent.html",
        task_items=task_items,
        per_task_limit=RECENT_DOWNLOADS_PER_TASK,
    )

# ---------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------

@app.route("/tasks", methods=["GET", "POST"])
def tasks():
    if request.method == "POST":
        # IMPORTANT: do NOT touch /downloads here.
        ensure_data_dirs(ensure_downloads=False)

        name = request.form.get("name", "").strip()
        urls_text = request.form.get("urls", "").strip()
        schedule = request.form.get("schedule", "").strip()
        command = request.form.get("command", "").strip()

        if not name:
            flash("Task name is required.", "error")
            return redirect(url_for("tasks"))

        keep_existing_urls = request.form.get("keep_existing_urls", "0") == "1"
        urls_upload = request.files.get("urls_file")

        if not keep_existing_urls:
            if urls_upload and urls_upload.filename:
                raw_urls = urls_upload.read(10 * 1024 * 1024 + 1)
                if len(raw_urls) > 10 * 1024 * 1024:
                    flash("URLs file too large (max 10 MB).", "error")
                    return redirect(url_for("tasks"))
                urls_text = raw_urls.decode("utf-8", errors="replace")
            elif urls_text:
                url_lines = [l for l in urls_text.splitlines() if l.strip()]
                if len(url_lines) > 100:
                    flash(
                        f"Too many URLs ({len(url_lines)}). Paste supports a max of 100 — "
                        "upload a .txt file instead for larger lists.",
                        "error",
                    )
                    return redirect(url_for("tasks"))
            else:
                flash("You need to provide at least one URL.", "error")
                return redirect(url_for("tasks"))

        slug = slugify(name)
        task_folder = os.path.join(TASKS_ROOT, slug)

        editing_flag = request.form.get("editing_flag") == "1"
        original_slug = request.form.get("original_slug", "").strip()
        if editing_flag and original_slug and original_slug != slug:
            old_folder = os.path.join(TASKS_ROOT, original_slug)
            if os.path.isdir(old_folder):
                if os.path.isdir(task_folder):
                    flash(f"A task named '{name}' already exists.", "error")
                    return redirect(url_for("tasks", selected=original_slug))
                os.rename(old_folder, task_folder)

        os.makedirs(task_folder, exist_ok=True)

        write_text(os.path.join(task_folder, "name.txt"), name)
        if not keep_existing_urls:
            write_text(os.path.join(task_folder, "urls.txt"), urls_text.strip() + "\n")

        if schedule:
            if not croniter.is_valid(schedule):
                flash(f"Invalid cron expression '{schedule}' — task saved without a schedule.", "warning")
                schedule = ""
        if schedule:
            write_text(os.path.join(task_folder, "cron.txt"), schedule)
        else:
            cron_path = os.path.join(task_folder, "cron.txt")
            if os.path.exists(cron_path):
                os.remove(cron_path)

        if not command:
            command = "gallery-dl --input-file urls.txt"

        try:
            parts = shlex.split(command)
            if parts and parts[0] == "gallery-dl":
                has_config_flag = any(
                    (p in ("-c", "--config") or p.startswith("--config=")) for p in parts
                )
                has_dest_flag = any(
                    (p in ("-d", "--destination") or p.startswith("--destination=")) for p in parts
                )

                insert_index = 1
                if not has_config_flag:
                    parts.insert(insert_index, "--config")
                    parts.insert(insert_index + 1, CONFIG_FILE)
                    insert_index += 2

                if not has_dest_flag:
                    parts.insert(insert_index, "--destination")
                    parts.insert(insert_index + 1, DOWNLOADS_ROOT)

                command = " ".join(shlex.quote(p) for p in parts)
        except ValueError as exc:
            app.logger.warning("Could not parse task command '%s': %s", command, exc)

        write_text(os.path.join(task_folder, "command.txt"), command)

        cookies_file = request.files.get("cookies_file")
        cookies_path = os.path.join(task_folder, "cookies.txt")
        if cookies_file and cookies_file.filename:
            raw = cookies_file.read(1 * 1024 * 1024 + 1)
            if len(raw) > 1 * 1024 * 1024:
                flash("Cookies file too large (max 1 MB).", "error")
                return redirect(url_for("tasks", selected=slug))
            text_preview = raw[:512].decode("utf-8", errors="replace")
            first_line = text_preview.lstrip().split("\n")[0].strip()
            if first_line and not first_line.startswith("#") and "\t" not in first_line:
                flash("Cookies file doesn't look like a valid Netscape cookies file.", "error")
                return redirect(url_for("tasks", selected=slug))
            with open(cookies_path, "wb") as _cf:
                _cf.write(raw)

        if "--cookies" in command and not os.path.exists(cookies_path):
            flash("Warning: command uses --cookies but no cookies.txt file exists for this task. Upload one via the edit form.", "warning")

        logs_path = os.path.join(task_folder, "logs.txt")
        if not os.path.exists(logs_path):
            write_text(logs_path, "")

        if schedule:
            _reschedule_task(slug, schedule)
        else:
            _unschedule_task(slug)
        _invalidate_task_cache()
        flash("Task created (or updated).", "success")
        return redirect(url_for("tasks", selected=slug))

    ensure_data_dirs(ensure_downloads=False)
    tasks_list = load_tasks()
    return render_template("tasks.html", tasks=tasks_list)


@app.route("/api/tasks")
def api_tasks():
    """Return a lightweight JSON representation of tasks for front-end polling."""
    ensure_data_dirs(ensure_downloads=False)
    tasks = load_tasks()

    out = []
    for t in tasks:
        out.append({
            "id": t.get("id"),
            "name": t.get("name"),
            "slug": t.get("slug"),
            "schedule": t.get("schedule"),
            "next_run": t.get("next_run"),
            "status": t.get("status"),
            "last_run": t.get("last_run"),
            "has_archive": t.get("has_archive", False),
            "has_cookies": t.get("has_cookies", False),
        })

    return jsonify(out)

# ---------------------------------------------------------------------
# Config page
# ---------------------------------------------------------------------

@app.route("/config", methods=["GET", "POST"])
def config_page():
    ensure_data_dirs(ensure_downloads=False)
    config_text = read_text(CONFIG_FILE) or ""
    scan_cron = _get_media_wall_scan_cron()

    if request.method == "POST":
        action = request.form.get("action")
        if action == "save":
            config_text = request.form.get("config_text", "")
            write_text(CONFIG_FILE, config_text)
            flash("Config saved.", "success")
        elif action == "reset":
            try:
                with urllib.request.urlopen(DEFAULT_CONFIG_URL, timeout=10) as resp:
                    default_text = resp.read().decode("utf-8")
                config_text = default_text
                write_text(CONFIG_FILE, config_text)
                flash("Default gallery-dl config downloaded from GitHub.", "success")
            except Exception as exc:
                flash(f"Failed to fetch default config: {exc}", "error")
        elif action == "mediawall_settings":
            raw = request.form.get("media_wall_scan_cron", "").strip()
            if croniter.is_valid(raw):
                _set_media_wall_scan_cron(raw)
                scan_cron = raw
                flash("Media wall schedule saved.", "success")
            else:
                flash("Invalid cron schedule.", "error")

    return render_template(
        "config.html",
        config_text=config_text,
        config_path=CONFIG_FILE,
        media_wall_enabled=MEDIA_WALL_ENABLED,
        media_wall_scan_cron=scan_cron,
        tasks=load_tasks(),
    )

# ---------------------------------------------------------------------
# Backup / Restore
# ---------------------------------------------------------------------

@app.route("/config/backup", methods=["POST"])
def config_backup():
    ensure_data_dirs(ensure_downloads=False)
    selected_slugs = request.form.getlist("slugs")
    include_config = request.form.get("include_config") == "1"

    SKIP_FILES = {"lock", "pid", "stopped"}
    stamp = dt.datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%S")
    zip_name = f"artillery-backup-{stamp}.zip"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for slug in selected_slugs:
            if not is_valid_slug(slug):
                continue
            task_dir = os.path.join(TASKS_ROOT, slug)
            if not os.path.isdir(task_dir):
                continue
            for fn in os.listdir(task_dir):
                if fn in SKIP_FILES:
                    continue
                fp = os.path.join(task_dir, fn)
                if os.path.isfile(fp):
                    zf.write(fp, f"tasks/{slug}/{fn}")

        if include_config and os.path.isfile(CONFIG_FILE):
            zf.write(CONFIG_FILE, f"config/{os.path.basename(CONFIG_FILE)}")

        if os.path.isdir(KIOSKS_ROOT):
            for kname in os.listdir(KIOSKS_ROOT):
                kdir = os.path.join(KIOSKS_ROOT, kname)
                if not os.path.isdir(kdir):
                    continue
                for root, _dirs, files in os.walk(kdir):
                    for fn in files:
                        fp = os.path.join(root, fn)
                        arcname = "config/kiosks/" + kname + "/" + os.path.relpath(fp, kdir)
                        zf.write(fp, arcname)

    buf.seek(0)
    return send_file(buf, mimetype="application/zip", as_attachment=True, download_name=zip_name)


@app.route("/config/restore", methods=["POST"])
def config_restore():
    ensure_data_dirs(ensure_downloads=False)
    f = request.files.get("backup_zip")
    if not f or not f.filename.endswith(".zip"):
        flash("Please upload a valid .zip backup file.", "error")
        return redirect(url_for("config_page"))

    raw = f.read(200 * 1024 * 1024 + 1)
    if len(raw) > 200 * 1024 * 1024:
        flash("Backup file too large (max 200 MB).", "error")
        return redirect(url_for("config_page"))

    restored_tasks, restored_kiosks = [], []
    restored_config = False

    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            for info in zf.infolist():
                name = info.filename.replace("\\", "/")
                if ".." in name or name.startswith("/"):
                    app.logger.warning("Backup restore: skipping unsafe path %s", name)
                    continue

                if name.startswith("tasks/") and not name.endswith("/"):
                    parts = name.split("/")
                    if len(parts) >= 3:
                        slug = parts[1]
                        if is_valid_slug(slug):
                            dest = os.path.join(TASKS_ROOT, slug, "/".join(parts[2:]))
                            os.makedirs(os.path.dirname(dest), exist_ok=True)
                            with zf.open(info) as src, open(dest, "wb") as dst:
                                dst.write(src.read())
                            if slug not in restored_tasks:
                                restored_tasks.append(slug)

                elif name.startswith("config/kiosks/") and not name.endswith("/"):
                    parts = name.split("/")
                    if len(parts) >= 4:
                        kname = parts[2]
                        if is_valid_slug(kname):
                            rel = "/".join(parts[3:])
                            dest = os.path.join(KIOSKS_ROOT, kname, rel)
                            os.makedirs(os.path.dirname(dest), exist_ok=True)
                            with zf.open(info) as src, open(dest, "wb") as dst:
                                dst.write(src.read())
                            if kname not in restored_kiosks:
                                restored_kiosks.append(kname)

                elif name.startswith("config/") and not name.endswith("/") and "kiosks" not in name:
                    fn = os.path.basename(name)
                    if fn:
                        dest = os.path.join(CONFIG_ROOT, fn)
                        with zf.open(info) as src, open(dest, "wb") as dst:
                            dst.write(src.read())
                        restored_config = True

    except zipfile.BadZipFile:
        flash("Invalid or corrupted zip file.", "error")
        return redirect(url_for("config_page"))
    except Exception as exc:
        app.logger.exception("Backup restore failed")
        flash(f"Restore failed: {exc}", "error")
        return redirect(url_for("config_page"))

    for slug in restored_tasks:
        cron_expr = read_text(os.path.join(TASKS_ROOT, slug, "cron.txt"))
        if cron_expr and cron_expr.strip():
            _reschedule_task(slug, cron_expr.strip())
    _invalidate_task_cache()

    parts = []
    if restored_tasks:
        parts.append(f"{len(restored_tasks)} task(s): {', '.join(restored_tasks)}")
    if restored_config:
        parts.append("gallery-dl config")
    if restored_kiosks:
        parts.append(f"{len(restored_kiosks)} kiosk(s)")
    flash("Restored: " + ("; ".join(parts) if parts else "nothing found in zip."), "success")
    return redirect(url_for("config_page"))

@app.route("/one-time", methods=["GET", "POST"])
def one_time_download():
    ensure_data_dirs(ensure_downloads=True)
    entered_url = ""
    status = _get_one_time_status()

    if request.method == "POST":
        entered_url = request.form.get("url", "").strip()
        if status["running"]:
            flash("A one-time download is already running.", "error")
            return redirect(url_for("one_time_download"))
        if not entered_url:
            flash("Please enter a URL.", "error")
            return redirect(url_for("one_time_download"))
        if shutil.which("gallery-dl") is None:
            flash("gallery-dl is not available on the PATH.", "error")
            return redirect(url_for("one_time_download"))

        try:
            if os.path.exists(ONE_TIME_STOP_FILE):
                os.remove(ONE_TIME_STOP_FILE)
        except Exception:
            app.logger.debug("Could not remove stale one-time stop file before start")

        thread = threading.Thread(target=run_one_time_download, args=(entered_url,), daemon=True)
        thread.start()
        flash("One-time download started in the background.", "success")
        return redirect(url_for("one_time_download"))

    return render_template(
        "one_time.html",
        config_path=CONFIG_FILE,
        download_root=DOWNLOADS_ROOT,
        entered_url=entered_url,
        running=status["running"],
    )

@app.route("/one-time/logs")
def one_time_logs():
    ensure_data_dirs(ensure_downloads=False)
    tail = request.args.get("tail", type=int)
    content = ""
    try:
        if os.path.exists(ONE_TIME_LOG_FILE):
            if tail and tail > 0:
                content = "\n".join(_tail_lines(ONE_TIME_LOG_FILE, tail))
            else:
                content = read_text(ONE_TIME_LOG_FILE) or ""
        else:
            content = "No logs yet."
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    return jsonify({
        "running": _get_one_time_status()["running"],
        "content": content,
    })

@app.route("/one-time/logs/download")
def one_time_download_logs():
    ensure_data_dirs(ensure_downloads=False)
    if not os.path.exists(ONE_TIME_LOG_FILE):
        return jsonify({"error": "No one-time download log exists."}), 404
    try:
        return send_file(ONE_TIME_LOG_FILE, as_attachment=True, download_name="one_time_download.log")
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

@app.route("/one-time/recent")
def one_time_recent():
    ensure_data_dirs(ensure_downloads=False)
    items = _recent_downloads_from_log(ONE_TIME_LOG_FILE, ONE_TIME_RECENT_DOWNLOADS)
    out = []
    for item in items:
        item_url = url_for("media_file", subpath=item["rel"])
        out.append({
            "rel": item["rel"],
            "url": item_url,
            "filename": item.get("filename") or os.path.basename(item["rel"]),
            "is_image": item.get("ext") in IMAGE_EXTS,
            "is_video": item.get("ext") in VIDEO_EXTS,
        })
    return jsonify({"items": out})

@app.route("/one-time/status")
def one_time_status():
    status = _get_one_time_status()
    return jsonify({"running": status["running"]})

@app.route("/one-time/clear-logs", methods=["POST"])
def one_time_clear_logs():
    try:
        write_text(ONE_TIME_LOG_FILE, "")
        flash("One-time download log cleared.", "success")
    except Exception as exc:
        flash(f"Failed to clear one-time log: {exc}", "error")
    return redirect(url_for("one_time_download"))

@app.route("/one-time/stop", methods=["POST"])
def one_time_stop():
    status = _get_one_time_status()
    if not status["running"]:
        flash("No one-time download is currently running.", "info")
        return redirect(url_for("one_time_download"))

    pid_text = read_text(ONE_TIME_PID_FILE)
    if pid_text:
        try:
            pid = int(pid_text.strip())
            Path(ONE_TIME_STOP_FILE).touch()
            os.kill(pid, signal.SIGTERM)
            flash("Stop signal sent to one-time download.", "success")
        except ProcessLookupError:
            flash("One-time download process is not running.", "info")
        except Exception as exc:
            flash(f"Failed to stop one-time download: {exc}", "error")
    else:
        flash("Could not read one-time download PID.", "error")
    return redirect(url_for("one_time_download"))

# ---------------------------------------------------------------------
# Task actions
# ---------------------------------------------------------------------

def run_one_time_download(url: str):
    ensure_data_dirs(ensure_downloads=True)
    try:
        if os.path.exists(ONE_TIME_STOP_FILE):
            os.remove(ONE_TIME_STOP_FILE)
    except Exception:
        app.logger.debug("Could not remove one-time stop file before run")

    env = os.environ.copy()
    env["GALLERY_DL_CONFIG"] = CONFIG_FILE
    env["PATH"] = env.get("PATH", "") + os.pathsep + "/usr/local/bin"

    cmd_parts = [
        "gallery-dl",
        "--config",
        CONFIG_FILE,
        "--destination",
        DOWNLOADS_ROOT,
        url,
    ]

    now = dt.datetime.utcnow().isoformat() + "Z"
    try:
        with open(ONE_TIME_LOG_FILE, "a", encoding="utf-8") as logf:
            logf.write(f"\n\n==== One-time download started at {now} ====\n")
            logf.write(f"URL: {url}\n")
            logf.write(f"Command: {' '.join(shlex.quote(p) for p in cmd_parts)}\n\n")
            logf.flush()

            proc = subprocess.Popen(
                cmd_parts,
                stdout=logf,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
            )
            try:
                Path(ONE_TIME_PID_FILE).write_text(str(proc.pid))
            except Exception:
                app.logger.warning("Could not write one-time PID file", exc_info=True)

            while proc.poll() is None:
                if os.path.exists(ONE_TIME_STOP_FILE):
                    try:
                        proc.terminate()
                        logf.write("\nStop requested. Terminating one-time download...\n")
                        logf.flush()
                    except Exception:
                        app.logger.warning("Could not terminate one-time download process", exc_info=True)
                time.sleep(0.25)

            returncode = proc.returncode

        with open(ONE_TIME_LOG_FILE, "a", encoding="utf-8") as logf:
            if returncode == 0:
                logf.write("\nOne-time download finished successfully.\n")
            else:
                logf.write(f"\nOne-time download exited with code {returncode}.\n")
    except Exception as exc:
        with open(ONE_TIME_LOG_FILE, "a", encoding="utf-8") as logf:
            logf.write(f"\nERROR while running one-time download: {exc}\n")
    finally:
        try:
            if os.path.exists(ONE_TIME_PID_FILE):
                os.remove(ONE_TIME_PID_FILE)
        except Exception:
            app.logger.debug("Could not remove one-time PID file in cleanup")
        try:
            if os.path.exists(ONE_TIME_STOP_FILE):
                os.remove(ONE_TIME_STOP_FILE)
        except Exception:
            app.logger.debug("Could not remove one-time stop file in cleanup")


def run_task_background(task_folder: str):
    ensure_data_dirs(ensure_downloads=True)

    lock_path     = os.path.join(task_folder, "lock")
    pid_path      = os.path.join(task_folder, "pid")
    stopped_path  = os.path.join(task_folder, "stopped")
    logs_path     = os.path.join(task_folder, "logs.txt")
    last_run_path = os.path.join(task_folder, "last_run.txt")
    command_path  = os.path.join(task_folder, "command.txt")
    urls_file     = os.path.join(task_folder, "urls.txt")
    error_path    = os.path.join(task_folder, "error")

    # Rotate previous log and clear transient state before starting
    _rotate_logs(task_folder)
    _clear_last_error(task_folder)
    try:
        if os.path.exists(error_path):
            os.remove(error_path)
    except Exception:
        app.logger.warning("Could not remove error sentinel for %s", task_folder, exc_info=True)

    command = read_text(command_path)
    if not command:
        with open(logs_path, "a", encoding="utf-8") as logf:
            logf.write("\nNo command configured for this task.\n")
        if os.path.exists(lock_path):
            os.remove(lock_path)
        return

    if not os.path.exists(urls_file):
        with open(logs_path, "a", encoding="utf-8") as logf:
            logf.write("\nurls.txt not found for this task.\n")
        if os.path.exists(lock_path):
            os.remove(lock_path)
        return

    now = dt.datetime.utcnow().isoformat() + "Z"

    try:
        cmd_parts = shlex.split(command)
    except ValueError as exc:
        with open(logs_path, "a", encoding="utf-8") as logf:
            logf.write(f"\nFailed to parse command: {exc}\n")
        if os.path.exists(lock_path):
            os.remove(lock_path)
        return

    env = os.environ.copy()
    env["GALLERY_DL_CONFIG"] = CONFIG_FILE
    env["PATH"] = env.get("PATH", "") + os.pathsep + "/usr/local/bin"

    try:
        with open(logs_path, "a", encoding="utf-8") as logf:
            config_exists = os.path.exists(CONFIG_FILE)
            logf.write(f"\n\n==== Run at {now} ====\n")
            logf.write(f"Artillery: using config {CONFIG_FILE} (exists={config_exists})\n")
            logf.write(f"$ {' '.join(cmd_parts)}\n\n")
            logf.flush()

            proc = subprocess.Popen(
                cmd_parts,
                cwd=task_folder,
                stdout=logf,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
            )
            try:
                Path(pid_path).write_text(str(proc.pid))
            except Exception:
                app.logger.warning("Could not write PID file for %s", task_folder, exc_info=True)

            timeout = _get_task_timeout(task_folder)
            timed_out = False
            try:
                returncode = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                returncode = -1
                timed_out = True
                logf.write(f"\nTask killed: exceeded {timeout}s timeout.\n")
                logf.flush()

        run_end = dt.datetime.utcnow()
        duration = (run_end - dt.datetime.fromisoformat(now.rstrip("Z"))).total_seconds()
        write_text(last_run_path, now)

        was_stopped = os.path.exists(stopped_path)
        try:
            if was_stopped:
                os.remove(stopped_path)
        except Exception:
            app.logger.debug("Could not remove stopped sentinel for %s", task_folder)

        success = returncode == 0 and not timed_out
        with open(logs_path, "a", encoding="utf-8") as logf:
            if success:
                logf.write("\nTask finished successfully.\n")
            elif was_stopped:
                logf.write("\nTask stopped.\n")
            elif timed_out:
                logf.write(f"\nTask timed out after {timeout}s.\n")
                Path(error_path).touch()
                _write_last_error(task_folder, f"Timed out after {timeout}s.")
            else:
                logf.write(f"\nTask exited with code {returncode}.\n")
                Path(error_path).touch()
                tail = _tail_lines(logs_path, 8)
                _write_last_error(task_folder, "\n".join(tail))

        _record_run(task_folder, success=success, duration=duration, stopped=was_stopped)

    except Exception as exc:
        app.logger.exception("Unhandled error in run_task_background for %s", task_folder)
        with open(logs_path, "a", encoding="utf-8") as logf:
            logf.write(f"\nERROR while running task: {exc}\n")
        try:
            Path(error_path).touch()
            _write_last_error(task_folder, str(exc))
        except Exception:
            app.logger.warning("Could not write error sentinel after task crash for %s", task_folder, exc_info=True)
        _record_run(task_folder, success=False, duration=0, stopped=False)
    finally:
        for p in (lock_path, pid_path):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                app.logger.debug("Could not remove lock/pid file %s in cleanup", p)

        try:
            slug = os.path.basename(task_folder.rstrip("/"))
            _TASK_CACHE.pop(slug, None)
            _invalidate_task_cache()
            touch_mediawall_notify()
            app.logger.info("task %s finished", slug)
        except Exception:
            app.logger.exception("Error in post-run cleanup for %s", task_folder)


@app.route("/tasks/<slug>/action", methods=["POST"])
def task_action(slug):
    if not is_valid_slug(slug):
        flash("Invalid task identifier.", "error")
        return redirect(url_for("tasks"))
    ensure_data_dirs(ensure_downloads=False)
    action = request.form.get("action")
    task_folder = os.path.join(TASKS_ROOT, slug)

    if not os.path.isdir(task_folder):
        flash("Task not found.", "error")
        return redirect(url_for("tasks"))

    if action == "duplicate":
        src_name = read_text(os.path.join(task_folder, "name.txt")).strip() or slug
        base_name = f"{src_name} copy"
        new_name = base_name
        counter = 2
        while os.path.isdir(os.path.join(TASKS_ROOT, slugify(new_name))):
            new_name = f"{base_name} {counter}"
            counter += 1
        new_slug = slugify(new_name)
        new_folder = os.path.join(TASKS_ROOT, new_slug)
        os.makedirs(new_folder)
        for fname in ("urls.txt", "command.txt", "cron.txt", "cookies.txt"):
            src = os.path.join(task_folder, fname)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(new_folder, fname))
        write_text(os.path.join(new_folder, "name.txt"), new_name)
        write_text(os.path.join(new_folder, "logs.txt"), "")
        _invalidate_task_cache()
        flash(f"Task duplicated as '{new_name}'.", "success")
        return redirect(url_for("tasks", selected=new_slug))

    if action == "delete":
        try:
            shutil.rmtree(task_folder)
            _unschedule_task(slug)
            _invalidate_task_cache()
            flash(f"Task '{slug}' deleted.", "success")
        except Exception as exc:
            flash(f"Failed to delete task: {exc}", "error")
        return redirect(url_for("tasks"))

    if action == "run":
        paused_path = os.path.join(task_folder, "paused")
        if os.path.exists(paused_path):
            flash("Task is paused. Unpause it before running.", "error")
            return redirect(url_for("tasks", selected=slug))

        lock_path = os.path.join(task_folder, "lock")
        ensure_data_dirs(ensure_downloads=True)
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
        except FileExistsError:
            flash("Task is already running.", "error")
            return redirect(url_for("tasks", selected=slug))

        t = threading.Thread(target=run_task_background, args=(task_folder,), daemon=True)
        t.start()

        flash("Task started in background. Check logs.txt for progress.", "success")
        return redirect(url_for("tasks", selected=slug))

    if action == "pause":
        paused_path = os.path.join(task_folder, "paused")
        if os.path.exists(paused_path):
            os.remove(paused_path)
            flash("Task unpaused.", "success")
        else:
            Path(paused_path).touch()
            flash("Task paused.", "success")
        return redirect(url_for("tasks", selected=slug))

    if action == "stop":
        pid_path = os.path.join(task_folder, "pid")
        pid_text = read_text(pid_path)
        if not pid_text:
            flash("Task does not appear to be running.", "info")
            return redirect(url_for("tasks", selected=slug))
        try:
            Path(os.path.join(task_folder, "stopped")).touch()
            os.kill(int(pid_text), signal.SIGTERM)
            flash("Stop signal sent.", "success")
        except ProcessLookupError:
            flash("Process already finished.", "info")
        except ValueError:
            flash("Invalid PID file.", "error")
        except Exception as exc:
            flash(f"Failed to stop task: {exc}", "error")
        return redirect(url_for("tasks", selected=slug))

    if action == "clear_logs":
        logs_path = os.path.join(task_folder, "logs.txt")
        try:
            write_text(logs_path, "")
            flash("Logs cleared.", "success")
        except Exception as exc:
            flash(f"Failed to clear logs: {exc}", "error")
        return redirect(url_for("tasks", selected=slug))

    if action == "delete_archive":
        archive_path = os.path.join(task_folder, "archive.sqlite")
        if os.path.exists(archive_path):
            try:
                os.remove(archive_path)
                flash("Archive deleted. gallery-dl will re-download previously seen items on next run.", "success")
            except Exception as exc:
                flash(f"Failed to delete archive: {exc}", "error")
            return redirect(url_for("tasks", selected=slug))
        else:
            flash("No archive file found for this task.", "info")
            return redirect(url_for("tasks", selected=slug))

    if action == "delete_cookies":
        cookies_path = os.path.join(task_folder, "cookies.txt")
        if os.path.exists(cookies_path):
            try:
                os.remove(cookies_path)
                flash("Cookies deleted.", "success")
            except Exception as exc:
                flash(f"Failed to delete cookies: {exc}", "error")
        else:
            flash("No cookies file found for this task.", "info")
        return redirect(url_for("tasks", selected=slug))

    flash("Unknown action.", "error")
    return redirect(url_for("tasks", selected=slug))

@app.route("/tasks/<slug>/logs")
def task_logs(slug):
    if not is_valid_slug(slug):
        return jsonify({"error": "Invalid task identifier"}), 400
    ensure_data_dirs(ensure_downloads=False)
    task_folder = os.path.join(TASKS_ROOT, slug)
    if not os.path.isdir(task_folder):
        return jsonify({"error": "Task not found"}), 404
    
    logs_path = os.path.join(task_folder, "logs.txt")

    try:
        if os.path.exists(logs_path):
            tail = request.args.get('tail', type=int)
            if tail and tail > 0:
                content = '\n'.join(_tail_lines(logs_path, tail))
            else:
                with open(logs_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
        else:
            content = "No logs yet. Task has not been run."
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    
    return jsonify({"slug": slug, "content": content})


# ---------------------------------------------------------------------
# Task URLs endpoint (lazy-loaded by the UI)
# ---------------------------------------------------------------------

@app.route("/tasks/<slug>/urls")
def task_urls(slug):
    if not is_valid_slug(slug):
        return jsonify({"error": "Invalid task identifier"}), 400
    ensure_data_dirs(ensure_downloads=False)
    task_folder = os.path.join(TASKS_ROOT, slug)
    if not os.path.isdir(task_folder):
        return jsonify({"error": "Task not found"}), 404
    urls_path = os.path.join(task_folder, "urls.txt")
    try:
        content = read_text(urls_path) or ""
        return jsonify({"slug": slug, "content": content})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/tasks/<slug>/history")
def task_history(slug):
    if not is_valid_slug(slug):
        return jsonify({"error": "Invalid task identifier"}), 400
    task_folder = os.path.join(TASKS_ROOT, slug)
    if not os.path.isdir(task_folder):
        return jsonify({"error": "Task not found"}), 404
    history_path = os.path.join(task_folder, "run_history.jsonl")
    runs = []
    if os.path.exists(history_path):
        try:
            with open(history_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            runs.append(json.loads(line))
                        except Exception:
                            app.logger.debug("Skipping malformed history line for %s: %s", slug, repr(line))
        except Exception:
            app.logger.warning("Could not read run history for %s", slug, exc_info=True)
    return jsonify({"slug": slug, "runs": list(reversed(runs[-50:]))})

@app.route("/tasks/<slug>/recent")
def task_recent(slug):
    if not is_valid_slug(slug):
        return jsonify({"error": "Invalid task identifier"}), 400
    ensure_data_dirs(ensure_downloads=False)
    task_folder = os.path.join(TASKS_ROOT, slug)
    if not os.path.isdir(task_folder):
        return jsonify({"error": "Task not found"}), 404
    log_path = os.path.join(task_folder, "logs.txt")
    items = _recent_downloads_from_log(log_path, RECENT_DOWNLOADS_PER_TASK)
    for item in items:
        item["url"] = url_for("media_file", subpath=item["rel"])
        item["is_image"] = item["ext"] in IMAGE_EXTS
        item["is_video"] = item["ext"] in VIDEO_EXTS
    return jsonify({"slug": slug, "items": items})


# ---------------------------------------------------------------------
# SSE log streaming
# ---------------------------------------------------------------------

@app.route("/tasks/<slug>/logs/stream")
def task_logs_stream(slug):
    if not is_valid_slug(slug):
        return Response("", status=400)
    task_folder = os.path.join(TASKS_ROOT, slug)
    if not os.path.isdir(task_folder):
        return Response("", status=404)

    def gen():
        logs_path = os.path.join(task_folder, "logs.txt")
        last_pos = 0
        if os.path.exists(logs_path):
            initial = "\n".join(_tail_lines(logs_path, 50))
            yield f"data: {json.dumps({'content': initial, 'reset': True})}\n\n"
            try:
                last_pos = os.path.getsize(logs_path)
            except Exception:
                app.logger.debug("Could not get initial size of log file %s", logs_path)
        else:
            yield f"data: {json.dumps({'content': '', 'reset': True})}\n\n"
        while True:
            try:
                time.sleep(1)
                if not os.path.exists(logs_path):
                    continue
                size = os.path.getsize(logs_path)
                if size < last_pos:
                    # log was cleared — re-send tail
                    initial = "\n".join(_tail_lines(logs_path, 50))
                    yield f"data: {json.dumps({'content': initial, 'reset': True})}\n\n"
                    last_pos = size
                elif size > last_pos:
                    with open(logs_path, "r", encoding="utf-8", errors="replace") as _lf:
                        _lf.seek(last_pos)
                        new_text = _lf.read()
                    last_pos = size
                    yield f"data: {json.dumps({'content': new_text, 'reset': False})}\n\n"
            except GeneratorExit:
                return
            except Exception:
                app.logger.debug("SSE stream error for %s", slug, exc_info=True)

    return Response(
        gen(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

# ---------------------------------------------------------------------
# Download task logs
# ---------------------------------------------------------------------
@app.route("/tasks/<slug>/logs/download")
def download_task_logs(slug):
    if not is_valid_slug(slug):
        return jsonify({"error": "Invalid task identifier"}), 400
    ensure_data_dirs(ensure_downloads=False)
    task_folder = os.path.join(TASKS_ROOT, slug)
    if not os.path.isdir(task_folder):
        return jsonify({"error": "Task not found"}), 404

    logs_path = os.path.join(task_folder, "logs.txt")
    if not os.path.exists(logs_path):
        return jsonify({"error": "No logs yet for this task"}), 404

    try:
        return send_file(logs_path, as_attachment=True, download_name=f"{slug}-logs.txt")
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

# ---------------------------------------------------------------------
# Archived (rotated) log listing and download
# ---------------------------------------------------------------------
_ARCHIVED_LOG_RE = re.compile(r'^logs-(\d{4}-\d{2}-\d{2}T\d{6})\.txt$')

@app.route("/tasks/<slug>/logs/archived")
def task_logs_archived(slug):
    if not is_valid_slug(slug):
        return jsonify({"error": "Invalid task identifier"}), 400
    task_folder = os.path.join(TASKS_ROOT, slug)
    if not os.path.isdir(task_folder):
        return jsonify({"error": "Task not found"}), 404
    files = []
    try:
        for fn in sorted(os.listdir(task_folder), reverse=True):
            m = _ARCHIVED_LOG_RE.match(fn)
            if m:
                fp = os.path.join(task_folder, fn)
                files.append({
                    "name": fn,
                    "ts": m.group(1),
                    "size": os.path.getsize(fp),
                })
    except Exception:
        app.logger.exception("Could not list archived logs for %s", slug)
    return jsonify({"slug": slug, "files": files})

@app.route("/tasks/<slug>/logs/archived/<filename>")
def download_task_log_archived(slug, filename):
    if not is_valid_slug(slug) or not _ARCHIVED_LOG_RE.match(filename):
        return jsonify({"error": "Invalid"}), 400
    task_folder = os.path.join(TASKS_ROOT, slug)
    fp = os.path.join(task_folder, filename)
    if not os.path.isfile(fp):
        return jsonify({"error": "Not found"}), 404
    try:
        return send_file(fp, as_attachment=True, download_name=f"{slug}-{filename}")
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

# ── Kiosk management ────────────────────────────────────────────────────────

@app.route("/kiosks", methods=["GET", "POST"])
def kiosks_list():
    ensure_data_dirs(ensure_downloads=False)
    os.makedirs(KIOSKS_ROOT, exist_ok=True)
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Kiosk name is required.", "error")
            return redirect(url_for("kiosks_list"))
        kslug = slugify(name)
        kdir = os.path.join(KIOSKS_ROOT, kslug)
        if os.path.isdir(kdir):
            flash(f"A kiosk named '{name}' already exists.", "error")
            return redirect(url_for("kiosks_list"))
        os.makedirs(os.path.join(kdir, "images"), exist_ok=True)
        _save_kiosk_settings(kslug, {
            "name": name,
            "interval": max(1, int(request.form.get("interval") or 10)),
            "order": request.form.get("order", "random"),
        })
        flash(f"Kiosk '{name}' created.", "success")
        return redirect(url_for("kiosk_manage", kslug=kslug))
    return render_template("kiosks.html", kiosks=_list_kiosks())


@app.route("/kiosks/<kslug>", methods=["GET", "POST"])
def kiosk_manage(kslug):
    if not is_valid_slug(kslug):
        flash("Invalid kiosk identifier.", "error")
        return redirect(url_for("kiosks_list"))
    ensure_data_dirs(ensure_downloads=False)
    kdir = os.path.join(KIOSKS_ROOT, kslug)
    if not os.path.isdir(kdir):
        flash("Kiosk not found.", "error")
        return redirect(url_for("kiosks_list"))

    if request.method == "POST":
        action = request.form.get("action")

        if action == "settings":
            settings = _kiosk_settings(kslug)
            settings["name"] = request.form.get("name", settings.get("name", kslug)).strip() or kslug
            settings["interval"] = max(1, int(request.form.get("interval") or 10))
            settings["order"] = request.form.get("order", "random")
            _save_kiosk_settings(kslug, settings)
            flash("Settings saved.", "success")

        elif action == "add_images":
            filenames = request.form.getlist("filenames")
            idir = os.path.join(kdir, "images")
            os.makedirs(idir, exist_ok=True)
            added = 0
            for fn in filenames:
                if "/" in fn or "\\" in fn or ".." in fn:
                    continue
                src = os.path.join(MEDIA_WALL_DIR, fn)
                dst = os.path.join(idir, fn)
                if os.path.isfile(src) and not os.path.exists(dst):
                    try:
                        shutil.copy2(src, dst)
                        added += 1
                    except Exception:
                        app.logger.warning("Could not copy media wall file to kiosk: %s", fn, exc_info=True)
            flash(f"Added {added} image(s) to kiosk.", "success")

        elif action == "remove_image":
            fn = request.form.get("filename", "")
            if "/" not in fn and "\\" not in fn and ".." not in fn and fn:
                fp = os.path.join(kdir, "images", fn)
                try:
                    if os.path.isfile(fp):
                        os.remove(fp)
                        flash("Image removed.", "success")
                except Exception:
                    app.logger.warning("Could not remove kiosk image %s", fn, exc_info=True)
                    flash("Could not remove image.", "error")

        return redirect(url_for("kiosk_manage", kslug=kslug))

    settings = _kiosk_settings(kslug)
    idir = os.path.join(kdir, "images")
    kiosk_images = []
    if os.path.isdir(idir):
        for fn in sorted(os.listdir(idir)):
            if os.path.isfile(os.path.join(idir, fn)):
                kiosk_images.append(fn)

    wall_images = []
    if os.path.isdir(MEDIA_WALL_DIR):
        kiosk_set = set(kiosk_images)
        for fn in sorted(os.listdir(MEDIA_WALL_DIR)):
            fp = os.path.join(MEDIA_WALL_DIR, fn)
            if not os.path.isfile(fp):
                continue
            ext = ("." + fn.rsplit(".", 1)[-1].lower()) if "." in fn else ""
            if ext in IMAGE_EXTS:
                wall_images.append({"name": fn, "in_kiosk": fn in kiosk_set})

    return render_template(
        "kiosk_manage.html",
        kslug=kslug,
        settings=settings,
        kiosk_images=kiosk_images,
        wall_images=wall_images,
    )


@app.route("/kiosks/<kslug>/delete", methods=["POST"])
def kiosk_delete(kslug):
    if not is_valid_slug(kslug):
        flash("Invalid kiosk identifier.", "error")
        return redirect(url_for("kiosks_list"))
    kdir = os.path.join(KIOSKS_ROOT, kslug)
    if os.path.isdir(kdir):
        try:
            shutil.rmtree(kdir)
            flash("Kiosk deleted.", "success")
        except Exception:
            app.logger.exception("Could not delete kiosk %s", kslug)
            flash("Failed to delete kiosk.", "error")
    return redirect(url_for("kiosks_list"))


# ── Kiosk display ────────────────────────────────────────────────────────────

@app.route("/kiosk/<kslug>")
def kiosk_display(kslug):
    if not is_valid_slug(kslug):
        return "Invalid kiosk", 400
    kdir = os.path.join(KIOSKS_ROOT, kslug)
    if not os.path.isdir(kdir):
        return "Kiosk not found", 404
    settings = _kiosk_settings(kslug)
    return render_template("kiosk_display.html", kslug=kslug, settings=settings)


@app.route("/kiosk/<kslug>/images")
def kiosk_images_api(kslug):
    if not is_valid_slug(kslug):
        return jsonify({"error": "Invalid"}), 400
    idir = os.path.join(KIOSKS_ROOT, kslug, "images")
    settings = _kiosk_settings(kslug)
    images = []
    if os.path.isdir(idir):
        for fn in os.listdir(idir):
            if os.path.isfile(os.path.join(idir, fn)):
                images.append({
                    "name": fn,
                    "url": url_for("kiosk_media", kslug=kslug, filename=fn),
                })
    return jsonify({
        "slug": kslug,
        "name": settings.get("name", kslug),
        "interval": settings.get("interval", 10),
        "order": settings.get("order", "random"),
        "images": images,
    })


@app.route("/kiosk/<kslug>/media/<filename>")
def kiosk_media(kslug, filename):
    if not is_valid_slug(kslug) or "/" in filename or "\\" in filename or ".." in filename:
        return "Invalid", 400
    idir = os.path.join(KIOSKS_ROOT, kslug, "images")
    return send_from_directory(idir, filename)

# ---------------------------------------------------------------------
# Original media route (serves from /downloads)
# ---------------------------------------------------------------------

@app.route("/media/<path:subpath>")
def media_file(subpath):
    ensure_data_dirs(ensure_downloads=True)
    return send_from_directory(DOWNLOADS_ROOT, subpath)

# ---------------------------------------------------------------------
# Main (dev only)
# ---------------------------------------------------------------------

# ── Start APScheduler (skip double-start under Werkzeug reloader) ──────────────
if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
    try:
        _load_all_schedules()
        _bg_scheduler.start()
        atexit.register(lambda: _bg_scheduler.shutdown(wait=False))
        app.logger.info("APScheduler started; %d job(s) loaded.", len(_bg_scheduler.get_jobs()))
    except Exception as _e:
        app.logger.warning("APScheduler failed to start: %s", _e)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
