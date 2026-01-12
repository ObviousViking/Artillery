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
import sqlite3
import hashlib
from collections import deque
from typing import Optional, List, Tuple

from flask import (
    Flask, render_template, request,
    redirect, url_for, flash, send_from_directory, Response
)
from flask import send_file

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
ARTILLERY_CONFIG_FILE = os.path.join(CONFIG_ROOT, "artillery.conf")

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

MEDIA_DB = os.path.join(CONFIG_ROOT, "mediawall.sqlite")
MEDIA_WALL_DIR = os.path.join(CONFIG_ROOT, "media_wall")

from werkzeug.exceptions import NotFound
from flask import jsonify

MEDIA_WALL_DIR_PREV = os.path.join(CONFIG_ROOT, "media_wall_prev")
MEDIA_WALL_DIR_NEXT = os.path.join(CONFIG_ROOT, "media_wall_next")

MEDIA_WALL_REFRESH_LOCK = threading.Lock()

# Disable aggressive caching of send_from_directory responses
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0


MEDIA_WALL_ROWS = 3
MEDIA_WALL_ENABLED = os.environ.get("MEDIA_WALL_ENABLED", "1") == "1"
MEDIA_WALL_ITEMS_ON_PAGE = int(os.environ.get("MEDIA_WALL_ITEMS", "45"))  # what homepage shows
MEDIA_WALL_CACHE_VIDEOS = os.environ.get("MEDIA_WALL_CACHE_VIDEOS", "0") == "1"

# Your requirement: copy up to 100 files into cache after task completion
MEDIA_WALL_COPY_LIMIT = int(os.environ.get("MEDIA_WALL_COPY_LIMIT", "100"))

# Auto behavior on task completion
MEDIA_WALL_AUTO_INGEST_ON_TASK_END = os.environ.get("MEDIA_WALL_AUTO_INGEST_ON_TASK_END", "1") == "1"
MEDIA_WALL_AUTO_REFRESH_ON_TASK_END = os.environ.get("MEDIA_WALL_AUTO_REFRESH_ON_TASK_END", "1") == "1"

# Throttle refresh to avoid copying 100 files for every task finish in rapid succession
MEDIA_WALL_MIN_REFRESH_SECONDS = int(os.environ.get("MEDIA_WALL_MIN_REFRESH_SECONDS", "300"))

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
    os.makedirs(MEDIA_WALL_DIR_PREV, exist_ok=True)
    os.makedirs(MEDIA_WALL_DIR_NEXT, exist_ok=True)


    if ensure_downloads:
        os.makedirs(DOWNLOADS_ROOT, exist_ok=True)

    if DEBUG_FS_TIMING and t0 is not None:
        ms = (time.perf_counter() - t0) * 1000
        app.logger.info("ensure_data_dirs(downloads=%s) %.1fms", ensure_downloads, ms)


def read_text(path: str):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip() or None


def write_text(path: str, content: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def load_artillery_config() -> dict:
    """Load Artillery configuration settings."""
    ensure_data_dirs(ensure_downloads=False)
    config = {
        "log_lines_display": 50,  # default
        "error_lines_display": 20,  # default
        "gallery_dl_progress": True,  # default: enable progress output
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
                        elif key == "gallery_dl_progress":
                            config["gallery_dl_progress"] = value.lower() in ("true", "1", "yes", "on")
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
            f.write(f"gallery_dl_progress={'true' if config.get('gallery_dl_progress', True) else 'false'}\n")
    except Exception as exc:
        app.logger.error("Failed to save Artillery config: %s", exc)
        raise


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
    os.makedirs(os.path.dirname(MEDIA_DB), exist_ok=True)

    conn = sqlite3.connect(MEDIA_DB, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS media (
            path TEXT PRIMARY KEY,
            ext  TEXT NOT NULL,
            task TEXT,
            first_seen TEXT NOT NULL,
            last_seen  TEXT NOT NULL,
            seen_count INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS task_offsets (
            task TEXT PRIMARY KEY,
            log_path TEXT NOT NULL,
            offset INTEGER NOT NULL DEFAULT 0,
            updated TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_media_ext ON media(ext);
        CREATE INDEX IF NOT EXISTS idx_media_last_seen ON media(last_seen);
    """)
    conn.commit()
    return conn


def _extract_relpath_from_log_line(line: str, downloads_root: str) -> Optional[str]:
    s = line.strip()
    if not s:
        return None

    s = s.replace("\\", "/")
    dr = downloads_root.replace("\\", "/").rstrip("/")

    if not (s == dr or s.startswith(dr + "/")):
        return None

    rel = s[len(dr):].lstrip("/")
    if not rel:
        return None

    ext = os.path.splitext(rel)[1].lower()
    if not ext or ext not in MEDIA_EXTS:
        return None

    return rel


def ingest_task_log(conn: sqlite3.Connection, task_slug: str, log_path: str, *, full_rescan: bool = False) -> Tuple[int, int]:
    start_offset = 0
    if not full_rescan:
        row = conn.execute(
            "SELECT offset FROM task_offsets WHERE task=? AND log_path=?",
            (task_slug, log_path),
        ).fetchone()
        if row:
            start_offset = int(row[0])

    try:
        with open(log_path, "rb") as f:
            if start_offset > 0:
                f.seek(start_offset)
            data = f.read()
            end_offset = f.tell()
    except OSError:
        return (0, 0)

    def upsert_offset(offset: int):
        conn.execute(
            """
            INSERT INTO task_offsets(task, log_path, offset, updated)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(task) DO UPDATE SET
                log_path=excluded.log_path,
                offset=excluded.offset,
                updated=excluded.updated
            """,
            (task_slug, log_path, int(offset), _utcnow()),
        )

    if not data:
        upsert_offset(start_offset)
        conn.commit()
        return (0, 0)

    text = data.decode("utf-8", errors="ignore")
    now = _utcnow()

    matched = 0
    inserted = 0

    for line in text.splitlines():
        rel = _extract_relpath_from_log_line(line, DOWNLOADS_ROOT)
        if not rel:
            continue

        matched += 1
        ext = os.path.splitext(rel)[1].lower()

        cur = conn.execute(
            """
            INSERT OR IGNORE INTO media(path, ext, task, first_seen, last_seen, seen_count)
            VALUES (?, ?, ?, ?, ?, 1)
            """,
            (rel, ext, task_slug, now, now),
        )
        if cur.rowcount == 1:
            inserted += 1
        else:
            conn.execute(
                """
                UPDATE media
                SET last_seen=?, task=?, ext=?, seen_count=seen_count + 1
                WHERE path=?
                """,
                (now, task_slug, ext, rel),
            )

    upsert_offset(end_offset)

    conn.execute(
        """
        INSERT INTO meta(key, value)
        VALUES ('last_ingest', ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        (now,),
    )
    conn.commit()
    return (matched, inserted)


def ingest_all_task_logs(conn: sqlite3.Connection, *, full_rescan: bool = False) -> dict:
    tasks_seen = 0
    matched_total = 0
    inserted_total = 0

    if not os.path.isdir(TASKS_ROOT):
        return {"tasks_seen": 0, "matched": 0, "inserted": 0}

    for slug in sorted(os.listdir(TASKS_ROOT)):
        task_dir = os.path.join(TASKS_ROOT, slug)
        if not os.path.isdir(task_dir):
            continue

        log_path = os.path.join(task_dir, "logs.txt")
        if not os.path.exists(log_path):
            continue

        tasks_seen += 1
        matched, inserted = ingest_task_log(conn, slug, log_path, full_rescan=full_rescan)
        matched_total += matched
        inserted_total += inserted

    return {"tasks_seen": tasks_seen, "matched": matched_total, "inserted": inserted_total}


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

    with MEDIA_WALL_REFRESH_LOCK:
        # choose candidates
        if MEDIA_WALL_CACHE_VIDEOS:
            rows = conn.execute(
                "SELECT path, ext FROM media ORDER BY RANDOM() LIMIT ?",
                (int(n),)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT path, ext FROM media WHERE ext IN ({}) ORDER BY RANDOM() LIMIT ?".format(
                    ",".join(["?"] * len(IMAGE_EXTS))
                ),
                tuple(sorted(IMAGE_EXTS)) + (int(n),)
            ).fetchall()

        picked = [(r[0], r[1]) for r in rows]
        if not picked:
            return {"picked": 0, "copied": 0, "failed": 0}

        # build next cache
        _clean_dir(MEDIA_WALL_DIR_NEXT)

        copied = 0
        failed = 0

        for rel, _ext in picked:
            src = os.path.join(DOWNLOADS_ROOT, rel)
            name = _cache_name_for_relpath(rel)
            dst = os.path.join(MEDIA_WALL_DIR_NEXT, name)

            tmp = dst + ".tmp"
            try:
                shutil.copy2(src, tmp)
                os.replace(tmp, dst)  # atomic file publish
                copied += 1
            except Exception as exc:
                failed += 1
                app.logger.warning("media wall copy failed: %s -> %s (%s)", src, dst, exc)
                try:
                    if os.path.exists(tmp):
                        os.remove(tmp)
                except Exception:
                    pass

        # if we copied nothing, don't swap (avoid wiping current wall)
        if copied == 0:
            return {"picked": len(picked), "copied": 0, "failed": failed}

        # rotate: delete old prev, move current->prev, next->current
        try:
            if os.path.isdir(MEDIA_WALL_DIR_PREV):
                shutil.rmtree(MEDIA_WALL_DIR_PREV)
        except Exception:
            pass

        try:
            if os.path.isdir(MEDIA_WALL_DIR):
                os.replace(MEDIA_WALL_DIR, MEDIA_WALL_DIR_PREV)
        except Exception:
            # if replace fails, we still try to proceed safely
            pass

        os.replace(MEDIA_WALL_DIR_NEXT, MEDIA_WALL_DIR)

        # recreate next dir for next run
        os.makedirs(MEDIA_WALL_DIR_NEXT, exist_ok=True)

        now = _utcnow()
        conn.execute(
            """
            INSERT INTO meta(key, value)
            VALUES ('last_cache_refresh', ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (now,),
        )
        conn.commit()

        return {"picked": len(picked), "copied": copied, "failed": failed}



def _should_refresh_cache(conn: sqlite3.Connection) -> bool:
    try:
        row = conn.execute("SELECT value FROM meta WHERE key='last_cache_refresh'").fetchone()
        if not row or not row[0]:
            return True
        last = row[0].replace("Z", "")
        last_dt = dt.datetime.fromisoformat(last)
        age = (dt.datetime.utcnow() - last_dt).total_seconds()
        return age >= MEDIA_WALL_MIN_REFRESH_SECONDS
    except Exception:
        return True


def get_mediawall_status(conn: sqlite3.Connection) -> dict:
    media_count = conn.execute("SELECT COUNT(*) FROM media").fetchone()[0]

    def _meta(k: str) -> Optional[str]:
        row = conn.execute("SELECT value FROM meta WHERE key=?", (k,)).fetchone()
        return row[0] if row else None

    return {
        "media_count": int(media_count),
        "last_ingest": _meta("last_ingest"),
        "last_cache_refresh": _meta("last_cache_refresh"),
    }

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
    """Toggle media wall enabled/disabled."""
    global MEDIA_WALL_ENABLED
    MEDIA_WALL_ENABLED = not MEDIA_WALL_ENABLED
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
                gallery_dl_progress = request.form.get("gallery_dl_progress", "off") == "on"
                artillery_config["log_lines_display"] = int(log_lines)
                artillery_config["error_lines_display"] = int(error_lines)
                artillery_config["gallery_dl_progress"] = gallery_dl_progress
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
    ensure_data_dirs(ensure_downloads=True)

    lock_path = os.path.join(task_folder, "lock")
    logs_path = os.path.join(task_folder, "logs.txt")
    last_run_path = os.path.join(task_folder, "last_run.txt")
    command_path = os.path.join(task_folder, "command.txt")
    urls_file = os.path.join(task_folder, "urls.txt")
    
    # Create logs directory for per-run logs
    logs_dir = os.path.join(task_folder, "logs")
    os.makedirs(logs_dir, exist_ok=True)

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
    # Create timestamped log file for this run
    timestamp = dt.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    run_log_path = os.path.join(logs_dir, f"run_{timestamp}.log")

    try:
        cmd_parts = shlex.split(command)
        
        # Load Artillery config to check gallery-dl progress setting
        artillery_config = load_artillery_config()
        progress_enabled = artillery_config.get("gallery_dl_progress", True)
        
        # Ensure progress output is enabled for gallery-dl (if configured)
        if cmd_parts and cmd_parts[0] == "gallery-dl":
            # Add --progress=off|on to control progress output
            # Check if progress flag already exists
            has_progress_flag = any(
                (p in ("--progress", "-p") or p.startswith("--progress=")) for p in cmd_parts
            )
            # If not specified, add based on Artillery config
            if not has_progress_flag:
                if progress_enabled:
                    cmd_parts.insert(1, "--progress=info")
                
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
        # Write header to both logs
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
            
            # Run the command and write to per-run log
            result = subprocess.run(
                cmd_parts,
                cwd=task_folder,
                stdout=run_logf,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
            )

        write_text(last_run_path, now)
        
        # Write completion status to per-run log
        footer = ""
        if result.returncode == 0:
            footer = "\nTask finished successfully.\n"
        else:
            footer = f"\nTask exited with code {result.returncode}.\n"
        
        with open(run_log_path, "a", encoding="utf-8") as run_logf:
            run_logf.write(footer)
        
        # Also append to main logs.txt using more efficient streaming
        with open(logs_path, "a", encoding="utf-8") as logf:
            with open(run_log_path, "r", encoding="utf-8", errors="replace") as run_logf:
                # Skip the header we already wrote by finding the command line
                for line in run_logf:
                    if line.startswith("$ "):
                        break  # Skip to next line after command
                # Stream remaining content efficiently
                shutil.copyfileobj(run_logf, logf)

    except Exception as exc:
        with open(logs_path, "a", encoding="utf-8") as logf:
            logf.write(f"\nERROR while running task: {exc}\n")
        with open(run_log_path, "a", encoding="utf-8") as run_logf:
            run_logf.write(f"\nERROR while running task: {exc}\n")
    finally:
        # ---- MEDIA WALL HOOK: ingest + refresh cache (copy up to 100) ----
        if MEDIA_WALL_AUTO_INGEST_ON_TASK_END:
            try:
                slug = os.path.basename(task_folder.rstrip("/"))
                conn = _open_media_db()  # creates DB if missing
                ingest_task_log(conn, slug, logs_path, full_rescan=False)

                if MEDIA_WALL_AUTO_REFRESH_ON_TASK_END and _should_refresh_cache(conn):
                    refresh_wall_cache(conn, min(MEDIA_WALL_COPY_LIMIT, 100))

                conn.close()
            except Exception as exc:
                app.logger.warning("Media wall update failed: %s", exc)

        if os.path.exists(lock_path):
            os.remove(lock_path)


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
        try:
            if os.path.exists(paused_path):
                os.remove(paused_path)
                # Ensure file removal is synced to disk
                os.sync() if hasattr(os, 'sync') else None
                flash("Task unpaused.", "success")
            else:
                # Create with explicit sync to ensure file is written to disk
                with open(paused_path, "w") as f:
                    f.write("")
                    f.flush()
                    os.fsync(f.fileno())
                # Ensure creation is synced to disk
                os.sync() if hasattr(os, 'sync') else None
                flash("Task paused.", "success")
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
    
    # Get the latest run log from the logs directory
    logs_dir = os.path.join(task_folder, "logs")
    run_log_path = None
    
    if os.path.isdir(logs_dir):
        # Find the most recent run log
        run_files = [
            f for f in os.listdir(logs_dir)
            if f.startswith("run_") and f.endswith(".log")
        ]
        if run_files:
            # Sort in reverse to get the latest (most recent timestamp)
            run_files.sort(reverse=True)
            run_log_path = os.path.join(logs_dir, run_files[0])
    
    def tail_lines(path: str, lines: int = 50) -> str:
        """Read the last N lines from a file without modifying content."""
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                all_lines = f.readlines()
                # Return last N lines, joined without extra newlines
                return ''.join(all_lines[-lines:]) if all_lines else ''
        except Exception:
            return ''

    try:
        if run_log_path and os.path.exists(run_log_path):
            tail = request.args.get('tail', type=int)
            if tail and tail > 0:
                content = tail_lines(run_log_path, tail)
            else:
                with open(run_log_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
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
    
    # Get the latest run log from the logs directory
    logs_dir = os.path.join(task_folder, "logs")
    run_log_path = None
    
    if os.path.isdir(logs_dir):
        # Find the most recent run log
        run_files = [
            f for f in os.listdir(logs_dir)
            if f.startswith("run_") and f.endswith(".log")
        ]
        if run_files:
            # Sort in reverse to get the latest (most recent timestamp)
            run_files.sort(reverse=True)
            run_log_path = os.path.join(logs_dir, run_files[0])
    
    # Get configured error lines limit
    artillery_config = load_artillery_config()
    max_error_lines = artillery_config.get("error_lines_display", 20)
    
    error_lines = deque(maxlen=max_error_lines)  # Efficiently maintain last N lines
    error_count = 0
    
    try:
        if run_log_path and os.path.exists(run_log_path):
            with open(run_log_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    # Check for gallery-dl error tags: [[error]] or Python exceptions
                    # Examples: [download][[error]] Failed to download...
                    #           [error] message
                    #           Traceback (most recent call last):
                    if re.search(r'\[\[error\]\]|\[error\]|^Traceback \(most recent call last\):|^[A-Z]\w*Error:', line, re.IGNORECASE):
                        error_count += 1
                        # Keep only last 20 error lines for display
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
        for filename in sorted(os.listdir(logs_dir), reverse=True):
            if filename.startswith("run_") and filename.endswith(".log"):
                filepath = os.path.join(logs_dir, filename)
                try:
                    stat = os.stat(filepath)
                    runs.append({
                        "filename": filename,
                        "size": stat.st_size,
                        "mtime": stat.st_mtime
                    })
                except Exception:
                    pass
    
    return jsonify({"slug": slug, "runs": runs})


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
