import os
import json
import datetime as dt
import re
import urllib.request
import urllib.parse
import shlex
import shutil
import threading
import time
import logging
import signal
import faulthandler
import sqlite3
import secrets
from collections import deque
from typing import Optional, Tuple

import task_runtime as tr
import mediawall_runtime as mw
from config import Config

from flask import (
    Flask, render_template, request,
    redirect, url_for, flash, send_from_directory, Response, session
)
from flask import jsonify
from werkzeug.exceptions import NotFound

# Load and validate configuration from environment variables
cfg = Config.from_env()

app = Flask(__name__)
app.config["SECRET_KEY"] = cfg.secret_key

# ---------------------------------------------------------------------
# Logging / Debug toggles
# ---------------------------------------------------------------------

logging.basicConfig(level=getattr(logging, cfg.log_level, logging.INFO))
app.logger.setLevel(getattr(logging, cfg.log_level, logging.INFO))

DEBUG_REQUEST_TIMING = cfg.debug_requests
DEBUG_FS_TIMING = cfg.debug_fs
HANG_DUMP_SECONDS = cfg.hang_dump_seconds

faulthandler.enable()
try:
    faulthandler.register(signal.SIGUSR1, all_threads=True)
except Exception:
    pass

if HANG_DUMP_SECONDS > 0:
    faulthandler.dump_traceback_later(HANG_DUMP_SECONDS, repeat=True)

# Log loaded configuration
app.logger.info("Artillery Configuration:")
app.logger.info(f"  Log Level: {cfg.log_level}")
app.logger.info(f"  Debug Requests: {DEBUG_REQUEST_TIMING}")
app.logger.info(f"  Debug FS: {DEBUG_FS_TIMING}")
app.logger.info(f"  Login Required: {cfg.login_required}")
app.logger.info(f"  Media Wall Enabled: {cfg.media_wall_enabled}")

# ---------------------------------------------------------------------
# Base data directories (shared with scheduler)
# ---------------------------------------------------------------------

TASKS_ROOT = str(cfg.tasks_dir)
CONFIG_ROOT = str(cfg.config_dir)
DOWNLOADS_ROOT = str(cfg.downloads_dir)

CONFIG_FILE = tr.CONFIG_FILE
ARTILLERY_CONFIG_FILE = os.path.join(CONFIG_ROOT, "artillery.conf")

DEFAULT_CONFIG_URL = cfg.default_config_url

IMAGE_EXTS = mw.IMAGE_EXTS
VIDEO_EXTS = mw.VIDEO_EXTS
MEDIA_EXTS = mw.MEDIA_EXTS

# Update task_runtime and mediawall_runtime with validated paths
os.environ["TASKS_DIR"] = TASKS_ROOT
os.environ["CONFIG_DIR"] = CONFIG_ROOT
os.environ["DOWNLOADS_DIR"] = DOWNLOADS_ROOT

# Re-import to pick up updated environment
import importlib
importlib.reload(tr)
importlib.reload(mw)

# Update references
TASKS_ROOT = tr.TASKS_ROOT
CONFIG_ROOT = tr.CONFIG_ROOT
DOWNLOADS_ROOT = tr.DOWNLOADS_ROOT

# ---------------------------------------------------------------------
# Media wall (DB + cache folder)
# ---------------------------------------------------------------------

MEDIA_DB = mw.MEDIA_DB
MEDIA_WALL_DIR = mw.MEDIA_WALL_DIR

MEDIA_WALL_DIR_PREV = mw.MEDIA_WALL_DIR_PREV
MEDIA_WALL_DIR_NEXT = mw.MEDIA_WALL_DIR_NEXT

MEDIA_WALL_REFRESH_LOCK = mw.MEDIA_WALL_REFRESH_LOCK

# Disable aggressive caching of send_from_directory responses
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

MEDIA_WALL_ROWS = 3
# Load media_wall_enabled from saved config, falling back to environment variable
_artillery_config = load_artillery_config()
MEDIA_WALL_ENABLED = _artillery_config.get("media_wall_enabled", cfg.media_wall_enabled)
MEDIA_WALL_ITEMS_ON_PAGE = cfg.media_wall_items_per_page
MEDIA_WALL_CACHE_VIDEOS = cfg.media_wall_cache_videos
MEDIA_WALL_COPY_LIMIT = cfg.media_wall_copy_limit
MEDIA_WALL_AUTO_INGEST_ON_TASK_END = cfg.media_wall_auto_ingest_on_task_end
MEDIA_WALL_AUTO_REFRESH_ON_TASK_END = cfg.media_wall_auto_refresh_on_task_end
MEDIA_WALL_MIN_REFRESH_SECONDS = cfg.media_wall_min_refresh_seconds

# ---------------------------------------------------------------------
# Optional login
# ---------------------------------------------------------------------

LOGIN_REQUIRED = cfg.login_required
LOGIN_USERNAME = cfg.login_username
LOGIN_PASSWORD = cfg.login_password

# Endpoints that should remain reachable even when login is required
LOGIN_EXEMPT_ENDPOINTS = {"login", "healthz", "static"}

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
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "") + "Z"


def slugify(name: str) -> str:
    name = name.strip().lower()
    name = re.sub(r"\s+", "-", name)
    name = re.sub(r"[^a-z0-9-]+", "", name)
    return name or "task"


ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def strip_ansi(text: Optional[str]) -> Optional[str]:
    """Remove ANSI escape sequences to prevent raw codes from showing in UI."""
    if text is None:
        return None
    return ANSI_ESCAPE_RE.sub("", text)


def _is_safe_redirect(target: Optional[str]) -> bool:
    """Ensure the redirect target stays on this host."""
    if not target:
        return False
    ref = urllib.parse.urlparse(request.host_url)
    test = urllib.parse.urlparse(urllib.parse.urljoin(request.host_url, target))
    return test.scheme in ("http", "https") and ref.netloc == test.netloc


@app.context_processor
def inject_globals():
    return {
        "login_required": LOGIN_REQUIRED,
    }


@app.before_request
def _enforce_login():
    if not LOGIN_REQUIRED:
        return

    # Allow essential endpoints without authentication
    if request.endpoint in LOGIN_EXEMPT_ENDPOINTS:
        return
    if request.path.startswith("/static/") or request.path == "/favicon.ico":
        return

    if session.get("authenticated"):
        return

    next_target = request.full_path if request.query_string else request.path
    return redirect(url_for("login", next=next_target))


# ---------------------------------------------------------------------
# Login / Logout
# ---------------------------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if not LOGIN_REQUIRED:
        return redirect(url_for("home"))

    if session.get("authenticated"):
        return redirect(url_for("home"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if secrets.compare_digest(username, LOGIN_USERNAME) and secrets.compare_digest(password, LOGIN_PASSWORD):
            session["authenticated"] = True
            session["username"] = username

            target = request.args.get("next")
            if not _is_safe_redirect(target):
                target = url_for("home")
            return redirect(target)

        flash("Invalid username or password.", "error")

    return render_template("login.html", body_class="login-body")


@app.route("/logout")
def logout():
    session.clear()
    if LOGIN_REQUIRED:
        flash("Signed out.", "success")
        return redirect(url_for("login"))
    return redirect(url_for("home"))


def _get_pid_for_task(slug: str, task_folder: str) -> Optional[int]:
    """Return PID of running task if known."""
    try:
        return tr._get_pid_for_task(slug, task_folder)
    except Exception:
        # Fall back to local pid file parsing (best effort)
        pid_path = os.path.join(task_folder, "pid")
        pid_text = read_text(pid_path)
        if not pid_text:
            return None
        try:
            return int(pid_text)
        except (TypeError, ValueError):
            return None


def _signal_task(slug: str, task_folder: str, sig) -> bool:
    """Send a signal to a running task process group. Returns True if delivered."""
    return tr.signal_task(slug, task_folder, sig)


def _cleanup_task_state(slug: str, task_folder: str):
    """Remove lock/pid and clear in-memory tracking."""
    tr.cleanup_task_state(slug, task_folder)


def _clear_stale_lock(slug: str, task_folder: str):
    """If lock exists but process is gone, clean up so task can run again."""
    tr.clear_stale_lock(slug, task_folder)


def _kill_task(slug: str, task_folder: str) -> bool:
    """Attempt to stop a running task politely, escalate if needed."""
    return tr.kill_task(slug, task_folder)


def ensure_data_dirs(ensure_downloads: bool = False):
    """
    Ensure base directories exist.

    CRITICAL: do not touch /downloads unless explicitly requested.
    """
    t0 = time.perf_counter() if DEBUG_FS_TIMING else None
    tr.ensure_data_dirs(ensure_downloads=ensure_downloads)

    if DEBUG_FS_TIMING and t0 is not None:
        ms = (time.perf_counter() - t0) * 1000
        app.logger.info("ensure_data_dirs(downloads=%s) %.1fms", ensure_downloads, ms)


def read_text(path: str, *, strip: bool = True) -> Optional[str]:
    """Read a UTF-8 text file safely.

    Uses errors='replace' to avoid crashing on corrupted log/config bytes.
    """
    return tr.read_text(path, strip=strip)


def write_text(path: str, content: str):
    """Atomically write UTF-8 text to disk (best effort)."""
    tr.write_text(path, content)


def _latest_run_log_path(task_dir: str) -> Optional[str]:
    logs_dir = os.path.join(task_dir, "logs")
    if not os.path.isdir(logs_dir):
        return None
    try:
        newest = None
        for entry in os.scandir(logs_dir):
            if not entry.is_file():
                continue
            name = entry.name
            if not (name.startswith("run_") and name.endswith(".log")):
                continue
            if newest is None or name > newest:
                newest = name
        return os.path.join(logs_dir, newest) if newest else None
    except Exception:
        return None


def _tail_lines_bounded(path: str, lines: int = 50, *, max_bytes: int = 2_000_000) -> str:
    """Read the last N lines efficiently (bounded by max_bytes)."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            start = max(0, size - int(max_bytes))
            f.seek(start)
            data = f.read()
        text = data.decode("utf-8", errors="replace")
        parts = text.splitlines()
        if not parts:
            return ""
        return "\n".join(parts[-int(lines):]) + "\n"
    except Exception:
        return ""


def _truncate_line_length(content: str, max_length: int) -> str:
    """Truncate each line to max_length characters, adding ... if truncated."""
    parts = content.split("\n")
    out = []
    for line in parts:
        if len(line) > max_length:
            out.append(line[:max_length] + "...")
        else:
            out.append(line)
    return "\n".join(out)


def load_artillery_config() -> dict:
    """Load Artillery configuration settings."""
    ensure_data_dirs(ensure_downloads=False)
    config = {
        "log_lines_display": 50,  # default
        "error_lines_display": 20,  # default
        "truncate_lines": True,  # default: enable line truncation
        "max_line_length": 200,  # default: max characters per line
        "media_wall_enabled": True,  # default: media wall enabled
    }
    
    if os.path.exists(ARTILLERY_CONFIG_FILE):
        try:
            with open(ARTILLERY_CONFIG_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, value = line.split("=", 1)
                        key = key.strip()
                        value = value.strip()
                        if key == "log_lines_display":
                            try:
                                config["log_lines_display"] = int(value)
                            except ValueError:
                                app.logger.warning("Invalid log_lines_display value '%s', using default", value)
                        elif key == "error_lines_display":
                            try:
                                config["error_lines_display"] = int(value)
                            except ValueError:
                                app.logger.warning("Invalid error_lines_display value '%s', using default", value)
                        elif key == "truncate_lines":
                            config["truncate_lines"] = value.lower() in ("true", "1", "yes", "on")
                        elif key == "max_line_length":
                            try:
                                config["max_line_length"] = int(value)
                            except ValueError:
                                app.logger.warning("Invalid max_line_length value '%s', using default", value)
                        elif key == "media_wall_enabled":
                            config["media_wall_enabled"] = value.lower() in ("true", "1", "yes", "on")
        except Exception as exc:
            app.logger.warning("Failed to load Artillery config: %s", exc)
    
    return config


def save_artillery_config(config: dict):
    """Save Artillery configuration settings."""
    ensure_data_dirs(ensure_downloads=False)
    try:
        with open(ARTILLERY_CONFIG_FILE, "w", encoding="utf-8") as f:
            f.write("# Artillery Configuration\n")
            f.write(f"log_lines_display={config.get('log_lines_display', 50)}\n")
            f.write(f"error_lines_display={config.get('error_lines_display', 20)}\n")
            f.write(f"truncate_lines={'true' if config.get('truncate_lines', True) else 'false'}\n")
            f.write(f"max_line_length={config.get('max_line_length', 200)}\n")
            f.write(f"media_wall_enabled={'true' if config.get('media_wall_enabled', True) else 'false'}\n")
    except Exception as exc:
        app.logger.error("Failed to save Artillery config: %s", exc)
        raise


def load_tasks():
    ensure_data_dirs(ensure_downloads=False)

    tasks = []
    if not os.path.isdir(TASKS_ROOT):
        return tasks

    try:
        entries = list(os.scandir(TASKS_ROOT))
    except Exception:
        entries = []

    for entry in sorted(entries, key=lambda e: e.name):
        if not entry.is_dir():
            continue

        slug = entry.name
        task_path = entry.path
        name = read_text(os.path.join(task_path, "name.txt")) or slug
        schedule = read_text(os.path.join(task_path, "cron.txt"))
        command = read_text(os.path.join(task_path, "command.txt")) or "gallery-dl --input-file urls.txt"
        last_run = read_text(os.path.join(task_path, "last_run.txt"))
        urls = read_text(os.path.join(task_path, "urls.txt"))

        lock_path = os.path.join(task_path, "lock")
        paused_path = os.path.join(task_path, "paused")

        # If paused flag exists, show paused even if a lock is present (running but halted)
        if os.path.exists(paused_path):
            status = "paused"
        elif os.path.exists(lock_path):
            status = "running"
        else:
            status = "idle"

        tasks.append({
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
        })

    return tasks

# ---------------------------------------------------------------------
# Media wall DB
# ---------------------------------------------------------------------

def _open_media_db() -> sqlite3.Connection:
    ensure_data_dirs(ensure_downloads=False)
    return mw.open_db(MEDIA_DB)


def _extract_relpath_from_log_line(line: str, downloads_root: str) -> Optional[str]:
    return mw.extract_relpath_from_log_line(line, downloads_root)


def ingest_task_log(conn: sqlite3.Connection, task_slug: str, log_path: str, *, full_rescan: bool = False) -> Tuple[int, int]:
    return mw.ingest_task_log(
        conn,
        task_slug,
        log_path,
        downloads_root=DOWNLOADS_ROOT,
        full_rescan=full_rescan,
    )


def ingest_all_task_logs(conn: sqlite3.Connection, *, full_rescan: bool = False) -> dict:
    return mw.ingest_all_task_logs(
        conn,
        tasks_root=TASKS_ROOT,
        downloads_root=DOWNLOADS_ROOT,
        full_rescan=full_rescan,
    )


def _cache_name_for_relpath(relpath: str) -> str:
    return mw._cache_name_for_relpath(relpath)


def _clean_dir(path: str):
    mw._clean_dir(path)


def refresh_wall_cache(conn: sqlite3.Connection, n: int) -> dict:
    """
    Pick up to N random items and copy them into cache.
    Refresh is atomic:
      - build new cache in MEDIA_WALL_DIR_NEXT
      - move current -> PREV
      - move NEXT -> current
    Old wall links remain valid for at least one refresh cycle via PREV fallback.
    """
    ensure_data_dirs(ensure_downloads=False)
    return mw.refresh_wall_cache(
        conn,
        n,
        downloads_root=DOWNLOADS_ROOT,
        cache_videos=MEDIA_WALL_CACHE_VIDEOS,
    )



def _should_refresh_cache(conn: sqlite3.Connection) -> bool:
    return mw.should_refresh_cache(conn)


def get_mediawall_status(conn: sqlite3.Connection) -> dict:
    return mw.get_status(conn)

# ---------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------

@app.route("/healthz")
def healthz():
    return Response("ok\n", mimetype="text/plain")

# ---------------------------------------------------------------------
# Media wall admin endpoints
# ---------------------------------------------------------------------

@app.route("/mediawall/status")
def mediawall_status():
    conn = _open_media_db()
    status = get_mediawall_status(conn)
    conn.close()
    return Response(json.dumps(status, indent=2) + "\n", mimetype="application/json")


@app.route("/mediawall/rebuild", methods=["POST"])
def mediawall_rebuild():
    conn = _open_media_db()
    stats = ingest_all_task_logs(conn, full_rescan=False)
    status = get_mediawall_status(conn)
    conn.close()
    flash(f"Media index updated: {stats} (total={status['media_count']})", "success")
    return redirect(url_for("home"))


@app.route("/mediawall/refresh", methods=["POST"])
def mediawall_refresh():
    conn = _open_media_db()
    result = refresh_wall_cache(conn, MEDIA_WALL_COPY_LIMIT)
    status = get_mediawall_status(conn)
    conn.close()
    flash(f"Media wall refreshed: {result} (total={status['media_count']})", "success")
    return redirect(url_for("home"))


@app.route("/mediawall/seed", methods=["POST"])
def mediawall_seed():
    """Convenience: rebuild then refresh."""
    if not MEDIA_WALL_ENABLED:
        flash("Media wall is disabled", "warning")
        return redirect(url_for("home"))
    conn = _open_media_db()
    stats = ingest_all_task_logs(conn, full_rescan=False)
    result = refresh_wall_cache(conn, MEDIA_WALL_COPY_LIMIT)
    status = get_mediawall_status(conn)
    conn.close()
    flash(f"Seeded wall. rebuild={stats} refresh={result} total={status['media_count']}", "success")
    return redirect(url_for("home"))


@app.route("/mediawall/toggle", methods=["POST"])
def mediawall_toggle():
    """Toggle media wall enabled/disabled and persist to config file."""
    global MEDIA_WALL_ENABLED
    MEDIA_WALL_ENABLED = not MEDIA_WALL_ENABLED
    status = "enabled" if MEDIA_WALL_ENABLED else "disabled"
    os.environ["MEDIA_WALL_ENABLED"] = "1" if MEDIA_WALL_ENABLED else "0"
    
    # Persist to artillery.conf
    try:
        config = load_artillery_config()
        config["media_wall_enabled"] = MEDIA_WALL_ENABLED
        save_artillery_config(config)
        app.logger.info(f"Media wall {status} and saved to configuration")
    except Exception as exc:
        app.logger.error(f"Failed to persist media wall setting: {exc}")
        # Still show flash even if save failed
    
    flash(f"Media wall {status}", "success")
    return redirect(url_for("config_page"))

# ---------------------------------------------------------------------
# Cached wall file route (fast: served from /config/media_wall)
# ---------------------------------------------------------------------

@app.route("/wall/<path:filename>")
def wall_file(filename):
    ensure_data_dirs(ensure_downloads=False)

    def _send(dirpath: str):
        resp = send_from_directory(dirpath, filename, conditional=True)
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        return resp

    try:
        return _send(MEDIA_WALL_DIR)
    except NotFound:
        return _send(MEDIA_WALL_DIR_PREV)
    


@app.route("/mediawall/api/cache_index")
def mediawall_cache_index():
    ensure_data_dirs(ensure_downloads=False)

    def _list_dir(d: str):
        items = []
        if not os.path.isdir(d):
            return items
        for entry in os.scandir(d):
            if not entry.is_file():
                continue
            fn = entry.name
            if fn.endswith(".tmp"):
                continue
            ext = os.path.splitext(fn)[1].lower()
            if ext not in MEDIA_EXTS:
                continue
            try:
                st = entry.stat()
            except FileNotFoundError:
                continue
            items.append({
                "name": fn,
                "mtime": int(st.st_mtime),
                "size": int(st.st_size),
                "url": url_for("wall_file", filename=fn),
            })
        items.sort(key=lambda x: x["mtime"], reverse=True)
        return items

    # primary list only (prev is fallback)
    return jsonify({
        "items": _list_dir(MEDIA_WALL_DIR),
    })


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
        cached_files = []
        try:
            for entry in os.scandir(MEDIA_WALL_DIR):
                if not entry.is_file():
                    continue
                fn = entry.name
                if fn.endswith(".tmp"):
                    continue
                if os.path.splitext(fn)[1].lower() not in MEDIA_EXTS:
                    continue
                cached_files.append(fn)
                if len(cached_files) >= MEDIA_WALL_ITEMS_ON_PAGE:
                    break
        except Exception:
            cached_files = []

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
    artillery_config = load_artillery_config()
    return render_template("tasks.html", tasks=tasks_list, artillery_config=artillery_config)

# ---------------------------------------------------------------------
# Config page
# ---------------------------------------------------------------------

@app.route("/config", methods=["GET", "POST"])
def config_page():
    ensure_data_dirs(ensure_downloads=False)
    config_text = read_text(CONFIG_FILE) or ""
    artillery_config = load_artillery_config()

    if request.method == "POST":
        action = request.form.get("action")
        if action == "save":
            config_text = request.form.get("config_text", "")
            write_text(CONFIG_FILE, config_text)
            flash("Config saved.", "success")
        elif action == "save_artillery":
            try:
                log_lines = request.form.get("log_lines_display", "50")
                error_lines = request.form.get("error_lines_display", "20")
                truncate_lines = request.form.get("truncate_lines", "off") == "on"
                max_line_length = request.form.get("max_line_length", "200")
                artillery_config["log_lines_display"] = int(log_lines)
                artillery_config["error_lines_display"] = int(error_lines)
                artillery_config["truncate_lines"] = truncate_lines
                artillery_config["max_line_length"] = int(max_line_length)
                save_artillery_config(artillery_config)
                flash("Artillery settings saved.", "success")
            except ValueError:
                flash("Invalid value. Both settings must be numbers.", "error")
            except Exception as exc:
                flash(f"Failed to save Artillery settings: {exc}", "error")
        elif action == "reset":
            try:
                with urllib.request.urlopen(DEFAULT_CONFIG_URL, timeout=10) as resp:
                    default_text = resp.read().decode("utf-8")
                config_text = default_text
                write_text(CONFIG_FILE, config_text)
                flash("Default gallery-dl config downloaded from GitHub.", "success")
            except Exception as exc:
                flash(f"Failed to fetch default config: {exc}", "error")

    return render_template("config.html", 
                         config_text=config_text, 
                         config_path=CONFIG_FILE, 
                         media_wall_enabled=MEDIA_WALL_ENABLED,
                         artillery_config=artillery_config)

# ---------------------------------------------------------------------
# Task actions
# ---------------------------------------------------------------------

def run_task_background(task_folder: str):
    # Delegate to the shared runtime module so scheduler.py doesn't need to import Flask.
    return tr.run_task_background(
        task_folder,
        media_wall_enabled=MEDIA_WALL_ENABLED,
        media_wall_cache_videos=MEDIA_WALL_CACHE_VIDEOS,
        media_wall_copy_limit=MEDIA_WALL_COPY_LIMIT,
        media_wall_auto_ingest=MEDIA_WALL_AUTO_INGEST_ON_TASK_END,
        media_wall_auto_refresh=MEDIA_WALL_AUTO_REFRESH_ON_TASK_END,
    )


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
        _clear_stale_lock(slug, task_folder)
        if os.path.exists(lock_path):
            flash("Task is already running.", "error")
            return redirect(url_for("tasks"))

        ensure_data_dirs(ensure_downloads=True)
        open(lock_path, "w").close()

        t = threading.Thread(target=run_task_background, args=(task_folder,), daemon=True)
        t.start()

        flash("Task started in background. Check logs.txt for progress.", "success")
        return redirect(url_for("tasks"))

    if action == "cancel":
        lock_path = os.path.join(task_folder, "lock")
        if not os.path.exists(lock_path):
            flash("Task is not running.", "error")
            return redirect(url_for("tasks"))

        if _kill_task(slug, task_folder):
            flash("Task canceled.", "success")
        else:
            flash("Failed to cancel task (process may have already exited or ignored signals).", "error")

        _clear_stale_lock(slug, task_folder)
        return redirect(url_for("tasks"))

    if action == "pause":
        paused_path = os.path.join(task_folder, "paused")
        try:
            if os.path.exists(paused_path):
                os.remove(paused_path)
                # Ensure file removal is synced to disk
                if hasattr(os, 'sync'):
                    os.sync()
                # Resume process if it's running and was previously stopped
                if _signal_task(slug, task_folder, signal.SIGCONT):
                    flash("Task unpaused and resumed.", "success")
                else:
                    _clear_stale_lock(slug, task_folder)
                    flash("Task unpaused (no running process).", "success")
            else:
                # Create with explicit sync to ensure file is written to disk
                with open(paused_path, "w") as f:
                    f.write("")
                    f.flush()
                    os.fsync(f.fileno())
                # Ensure creation is synced to disk
                if hasattr(os, 'sync'):
                    os.sync()
                # Send SIGSTOP to running process if present
                if _signal_task(slug, task_folder, signal.SIGSTOP):
                    flash("Task paused (process stopped).", "success")
                else:
                    _clear_stale_lock(slug, task_folder)
                    flash("Task paused (process not running).", "success")
        except Exception as exc:
            flash(f"Failed to pause/unpause task: {exc}", "error")
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
    Returns JSON with the log content from the current/latest run log.
    Per-run logs are stored in /tasks/<slug>/logs/run_YYYYMMDD_HHMMSS.log
    """
    ensure_data_dirs(ensure_downloads=False)
    
    task_folder = os.path.join(TASKS_ROOT, slug)
    if not os.path.isdir(task_folder):
        return jsonify({"error": "Task not found"}), 404
    
    run_log_path = _latest_run_log_path(task_folder)

    try:
        if run_log_path and os.path.exists(run_log_path):
            tail = request.args.get('tail', type=int)
            if tail and tail > 0:
                content = _tail_lines_bounded(run_log_path, tail)
            else:
                with open(run_log_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()

            content = strip_ansi(content)

            # Load Artillery config to check line truncation setting
            artillery_config = load_artillery_config()
            truncate_enabled = artillery_config.get("truncate_lines", True)
            
            # Apply line truncation if enabled
            if truncate_enabled:
                max_length = artillery_config.get("max_line_length", 200)
                content = _truncate_line_length(content, max_length)
        else:
            content = "No logs yet. Task has not been run."
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    
    return jsonify({"slug": slug, "content": content})


@app.route("/tasks/<slug>/errors")
def task_errors(slug):
    """
    Extract and return error lines from task logs (current run).
    Returns JSON with error lines and count from the latest run log.
    """
    ensure_data_dirs(ensure_downloads=False)
    
    task_folder = os.path.join(TASKS_ROOT, slug)
    if not os.path.isdir(task_folder):
        return jsonify({"error": "Task not found"}), 404
    
    run_log_path = _latest_run_log_path(task_folder)
    
    # Get configured error lines limit
    artillery_config = load_artillery_config()
    max_error_lines = artillery_config.get("error_lines_display", 20)
    
    error_lines = deque(maxlen=max_error_lines)  # Efficiently maintain last N lines
    error_count = 0

    error_re = re.compile(
        r"\[\[error\]\]|\[error\]|^Traceback \(most recent call last\):|^[A-Z]\w*Error:",
        re.IGNORECASE,
    )
    
    try:
        if run_log_path and os.path.exists(run_log_path):
            with open(run_log_path, "r", encoding="utf-8", errors="replace") as f:
                for raw_line in f:
                    line = strip_ansi(raw_line)
                    # Check for gallery-dl error tags: [[error]] or Python exceptions
                    # Examples: [download][[error]] Failed to download...
                    #           [error] message
                    #           Traceback (most recent call last):
                    if error_re.search(line):
                        error_count += 1
                        # Keep only the last configured error lines for display (max_error_lines)
                        error_lines.append(line.rstrip())
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    
    return jsonify({
        "slug": slug, 
        "error_count": error_count, 
        "error_lines": list(error_lines)
    })


@app.route("/tasks/<slug>/runs")
def task_runs(slug):
    """
    List available per-run log files for a task.
    Returns JSON with list of run logs.
    """
    ensure_data_dirs(ensure_downloads=False)
    
    task_folder = os.path.join(TASKS_ROOT, slug)
    if not os.path.isdir(task_folder):
        return jsonify({"error": "Task not found"}), 404
    
    logs_dir = os.path.join(task_folder, "logs")
    runs = []

    if os.path.isdir(logs_dir):
        try:
            for entry in os.scandir(logs_dir):
                if not entry.is_file():
                    continue
                filename = entry.name
                if not (filename.startswith("run_") and filename.endswith(".log")):
                    continue
                try:
                    stat = entry.stat()
                except FileNotFoundError:
                    continue
                runs.append({
                    "filename": filename,
                    "size": int(stat.st_size),
                    "mtime": float(stat.st_mtime),
                })
        except Exception:
            pass

    runs.sort(key=lambda r: r["filename"], reverse=True)
    
    return jsonify({"slug": slug, "runs": runs})


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
