import os
import json
import uuid  # unused for now
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
from typing import Optional, List, Tuple
from croniter import croniter

from flask import (
    Flask, render_template, request,
    redirect, url_for, flash, send_from_directory, Response
)
from flask import send_file, jsonify, url_for

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")

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
    pass

if HANG_DUMP_SECONDS > 0:
    faulthandler.dump_traceback_later(HANG_DUMP_SECONDS, repeat=True)

# ---------------------------------------------------------------------
# Base data directories
# ---------------------------------------------------------------------

TASKS_ROOT = os.environ.get("TASKS_DIR") or "/tasks"
CONFIG_ROOT = os.environ.get("CONFIG_DIR") or "/config"
DOWNLOADS_ROOT = os.environ.get("DOWNLOADS_DIR") or "/downloads"

CONFIG_FILE = os.path.join(CONFIG_ROOT, "gallery-dl.conf")

DEFAULT_CONFIG_URL = os.environ.get(
    "GALLERYDL_DEFAULT_CONFIG_URL",
    "https://raw.githubusercontent.com/mikf/gallery-dl/master/docs/gallery-dl.conf",
)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
VIDEO_EXTS = {".mp4", ".webm", ".mkv"}
MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS

# ---------------------------------------------------------------------
# Media wall (DB + cache folder)
# ---------------------------------------------------------------------

MEDIA_WALL_DIR = os.path.join(CONFIG_ROOT, "media_wall")
MEDIA_WALL_SCAN_CRON_FILE = os.path.join(CONFIG_ROOT, "mediawall_scan_cron.txt")
MEDIA_WALL_ENABLED_FILE = os.path.join(CONFIG_ROOT, "mediawall_enabled.txt")

from werkzeug.exceptions import NotFound

MEDIA_WALL_REFRESH_LOCK = threading.Lock()

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

# Media wall notify file for SSE
MEDIAWALL_NOTIFY_FILE = os.path.join(os.environ.get('CONFIG_DIR', '/config'), 'mediawall.notify')

def touch_mediawall_notify():
    try:
        os.makedirs(os.path.dirname(MEDIAWALL_NOTIFY_FILE), exist_ok=True)
        with open(MEDIAWALL_NOTIFY_FILE, 'a'):
            os.utime(MEDIAWALL_NOTIFY_FILE, None)
    except Exception:
        pass

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
    }

def _cache_name_for_relpath(relpath: str) -> str:
    ext = os.path.splitext(relpath)[1].lower()
    h = hashlib.sha1(relpath.encode("utf-8", errors="ignore")).hexdigest()
    return f"{h}{ext}"

def _clean_dir(path: str):
    os.makedirs(path, exist_ok=True)
    for fn in os.listdir(path):
        try:
            os.remove(os.path.join(path, fn))
        except Exception:
            pass

def _refresh_media_wall_cache_from_downloads() -> dict:
    ensure_data_dirs(ensure_downloads=True)

    allowed = set(IMAGE_EXTS)
    if MEDIA_WALL_CACHE_VIDEOS:
        allowed |= set(VIDEO_EXTS)

    with MEDIA_WALL_REFRESH_LOCK:
        items = []
        for root, _dirs, files in os.walk(DOWNLOADS_ROOT):
            for fn in files:
                ext = os.path.splitext(fn)[1].lower()
                if ext not in allowed:
                    continue
                path = os.path.join(root, fn)
                try:
                    mtime = os.path.getmtime(path)
                except Exception:
                    continue
                rel = os.path.relpath(path, DOWNLOADS_ROOT)
                items.append((mtime, rel))

        if not items:
            return {"picked": 0, "copied": 0}

        items.sort(key=lambda x: x[0], reverse=True)
        picked = items[:MEDIA_WALL_COPY_LIMIT]

        _clean_dir(MEDIA_WALL_DIR)

        copied = 0
        for _mtime, rel in picked:
            src = os.path.join(DOWNLOADS_ROOT, rel)
            dst = os.path.join(MEDIA_WALL_DIR, _cache_name_for_relpath(rel))
            tmp = dst + ".tmp"
            try:
                shutil.copy2(src, tmp)
                os.replace(tmp, dst)
                copied += 1
            except Exception:
                try:
                    if os.path.exists(tmp):
                        os.remove(tmp)
                except Exception:
                    pass

        return {"picked": len(picked), "copied": copied}

_MEDIA_WALL_SCAN_THREAD_STARTED = False

def _media_wall_scan_worker():
    last_minute = None

    # one-time warmup if enabled and cache empty
    if MEDIA_WALL_ENABLED and not os.listdir(MEDIA_WALL_DIR):
        _refresh_media_wall_cache_from_downloads()
        touch_mediawall_notify()

    while True:
        if not MEDIA_WALL_ENABLED:
            time.sleep(2)
            continue

        expr = _get_media_wall_scan_cron()
        now = dt.datetime.now()
        minute_key = now.strftime("%Y-%m-%d %H:%M")

        if croniter.match(expr, now) and minute_key != last_minute:
            last_minute = minute_key
            _refresh_media_wall_cache_from_downloads()
            touch_mediawall_notify()

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
        urls = read_text(os.path.join(task_path, "urls.txt"))

        lock_path = os.path.join(task_path, "lock")
        paused_path = os.path.join(task_path, "paused")

        if os.path.exists(lock_path):
            status = "running"
        elif os.path.exists(paused_path):
            status = "paused"
        else:
            status = "idle"

        task = {
            "id": slug,
            "name": name,
            "slug": slug,
            "schedule": schedule,
            "status": status,
            "last_run": last_run,
            "task_path": task_path,
            "urls_file": "urls.txt",
            "command": command,
            "urls": urls,
        }
        _TASK_CACHE[slug] = {"_mtimes": mtimes, "task": task}
        tasks.append(task)

    return tasks

# ---------------------------------------------------------------------
# Health check
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
    MEDIA_WALL_ENABLED = not MEDIA_WALL_ENABLED
    _set_media_wall_enabled(MEDIA_WALL_ENABLED)
    if MEDIA_WALL_ENABLED:
        _start_media_wall_scan_thread()
    status = "enabled" if MEDIA_WALL_ENABLED else "disabled"
    os.environ["MEDIA_WALL_ENABLED"] = "1" if MEDIA_WALL_ENABLED else "0"
    flash(f"Media wall {status}", "success")
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
        pass
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

        if not urls_text:
            flash("You need to provide at least one URL.", "error")
            return redirect(url_for("tasks"))

        slug = slugify(name)
        task_folder = os.path.join(TASKS_ROOT, slug)
        os.makedirs(task_folder, exist_ok=True)

        write_text(os.path.join(task_folder, "name.txt"), name)
        write_text(os.path.join(task_folder, "urls.txt"), urls_text.strip() + "\n")

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
        except ValueError:
            pass

        write_text(os.path.join(task_folder, "command.txt"), command)

        logs_path = os.path.join(task_folder, "logs.txt")
        if not os.path.exists(logs_path):
            write_text(logs_path, "")

        flash("Task created (or updated).", "success")
        return redirect(url_for("tasks"))

    ensure_data_dirs(ensure_downloads=False)
    tasks_list = load_tasks()
    return render_template("tasks.html", tasks=tasks_list)

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
    )

# ---------------------------------------------------------------------
# Task actions
# ---------------------------------------------------------------------

def run_task_background(task_folder: str):
    ensure_data_dirs(ensure_downloads=True)

    lock_path = os.path.join(task_folder, "lock")
    logs_path = os.path.join(task_folder, "logs.txt")
    last_run_path = os.path.join(task_folder, "last_run.txt")
    command_path = os.path.join(task_folder, "command.txt")
    urls_file = os.path.join(task_folder, "urls.txt")

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

            result = subprocess.run(
                cmd_parts,
                cwd=task_folder,
                stdout=logf,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
            )

        write_text(last_run_path, now)

        with open(logs_path, "a", encoding="utf-8") as logf:
            if result.returncode == 0:
                logf.write("\nTask finished successfully.\n")
            else:
                logf.write(f"\nTask exited with code {result.returncode}.\n")

    except Exception as exc:
        with open(logs_path, "a", encoding="utf-8") as logf:
            logf.write(f"\nERROR while running task: {exc}\n")
    finally:
        # Task completion: just notify clients that media wall should refresh
        if os.path.exists(lock_path):
            os.remove(lock_path)

        try:
            touch_mediawall_notify()
            slug = os.path.basename(task_folder.rstrip("/"))
            print(f"task {slug} finished", flush=True)
        except Exception:
            pass


@app.route("/tasks/<slug>/action", methods=["POST"])
def task_action(slug):
    ensure_data_dirs(ensure_downloads=False)
    action = request.form.get("action")
    task_folder = os.path.join(TASKS_ROOT, slug)

    if not os.path.isdir(task_folder):
        flash("Task not found.", "error")
        return redirect(url_for("tasks"))

    if action == "delete":
        try:
            shutil.rmtree(task_folder)
            flash(f"Task '{slug}' deleted.", "success")
        except Exception as exc:
            flash(f"Failed to delete task: {exc}", "error")
        return redirect(url_for("tasks"))

    if action == "run":
        paused_path = os.path.join(task_folder, "paused")
        if os.path.exists(paused_path):
            flash("Task is paused. Unpause it before running.", "error")
            return redirect(url_for("tasks"))

        lock_path = os.path.join(task_folder, "lock")
        if os.path.exists(lock_path):
            flash("Task is already running.", "error")
            return redirect(url_for("tasks"))

        ensure_data_dirs(ensure_downloads=True)
        open(lock_path, "w").close()

        t = threading.Thread(target=run_task_background, args=(task_folder,), daemon=True)
        t.start()

        flash("Task started in background. Check logs.txt for progress.", "success")
        return redirect(url_for("tasks"))

    if action == "pause":
        paused_path = os.path.join(task_folder, "paused")
        if os.path.exists(paused_path):
            os.remove(paused_path)
            flash("Task unpaused.", "success")
        else:
            open(paused_path, "w").close()
            flash("Task paused.", "success")
        return redirect(url_for("tasks"))

    flash("Unknown action.", "error")
    return redirect(url_for("tasks"))

# ---------------------------------------------------------------------
# Task logs endpoint
# ---------------------------------------------------------------------

@app.route("/tasks/<slug>/logs")
def task_logs(slug):
    """
    Fetch the log content for a task.
    Returns JSON with the log content and metadata.
    """
    ensure_data_dirs(ensure_downloads=False)
    
    task_folder = os.path.join(TASKS_ROOT, slug)
    if not os.path.isdir(task_folder):
        return jsonify({"error": "Task not found"}), 404
    
    logs_path = os.path.join(task_folder, "logs.txt")
    
    def tail_lines(path: str, lines: int = 50) -> str:
        try:
            with open(path, 'rb') as f:
                f.seek(0, os.SEEK_END)
                file_size = f.tell()
                block_size = 1024
                chunks = []
                lines_found = 0
                pos = file_size

                while pos > 0 and lines_found <= lines:
                    read_size = block_size if pos >= block_size else pos
                    pos -= read_size
                    f.seek(pos)
                    chunk = f.read(read_size)
                    chunks.append(chunk)
                    lines_found = b"\n".join(chunks).count(b"\n")

                data = b"".join(reversed(chunks))
                text = data.decode('utf-8', errors='replace')
                return '\n'.join(text.splitlines()[-lines:])
        except Exception:
            # Fallback to reading whole file if anything goes wrong
            try:
                with open(path, 'r', encoding='utf-8', errors='replace') as f:
                    return '\n'.join(f.read().splitlines()[-lines:])
            except Exception:
                return ''

    try:
        if os.path.exists(logs_path):
            tail = request.args.get('tail', type=int)
            if tail and tail > 0:
                content = tail_lines(logs_path, tail)
            else:
                with open(logs_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
        else:
            content = "No logs yet. Task has not been run."
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    
    return jsonify({"slug": slug, "content": content})


# ---------------------------------------------------------------------
# Download task logs
# ---------------------------------------------------------------------
@app.route("/tasks/<slug>/logs/download")
def download_task_logs(slug):
    ensure_data_dirs(ensure_downloads=False)

    task_folder = os.path.join(TASKS_ROOT, slug)
    if not os.path.isdir(task_folder):
        return jsonify({"error": "Task not found"}), 404

    logs_path = os.path.join(task_folder, "logs.txt")
    if not os.path.exists(logs_path):
        return jsonify({"error": "No logs yet for this task"}), 404

    try:
        # Prefer modern Flask's download_name, fallback to attachment_filename
        try:
            return send_file(logs_path, as_attachment=True, download_name=f"{slug}-logs.txt")
        except TypeError:
            return send_file(logs_path, as_attachment=True, attachment_filename=f"{slug}-logs.txt")
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
