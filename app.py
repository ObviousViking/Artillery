import os
import json
import uuid  # unused for now
import datetime as dt
import re
import urllib.request
import urllib.error
import subprocess
import shlex
import shutil
import threading
import time
import logging
import signal
import faulthandler
import sqlite3
from typing import Optional, List, Tuple

from flask import (
    Flask, render_template, request,
    redirect, url_for, flash, send_from_directory, Response
)

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

# If set, dump stack traces periodically (helps catch hangs)
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

# Media wall DB
MEDIA_DB = os.path.join(CONFIG_ROOT, "mediawall.sqlite")
MEDIA_WALL_ITEMS = int(os.environ.get("MEDIA_WALL_ITEMS", "45"))  # total thumbnails on wall
MEDIA_WALL_ROWS = 3  # template expects 3 rows currently
MEDIA_WALL_AUTO_INGEST_ON_TASK_END = os.environ.get("MEDIA_WALL_AUTO_INGEST_ON_TASK_END", "1") == "1"

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
# Media wall SQLite index (parses /tasks/*/logs.txt only)
# ---------------------------------------------------------------------

def _open_media_db() -> sqlite3.Connection:
    ensure_data_dirs(ensure_downloads=False)
    os.makedirs(os.path.dirname(MEDIA_DB), exist_ok=True)
    conn = sqlite3.connect(MEDIA_DB, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS media (
            path TEXT PRIMARY KEY,         -- relative to downloads root
            ext  TEXT NOT NULL,
            task TEXT,
            first_seen TEXT NOT NULL,
            last_seen  TEXT NOT NULL,
            seen_count INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS task_offsets (
            task TEXT PRIMARY KEY,         -- task slug
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
    """
    Accepts lines like:
      /downloads/site/artist/file.jpg
    Returns:
      site/artist/file.jpg
    """
    s = line.strip()
    if not s:
        return None

    s = s.replace("\\", "/")
    dr = downloads_root.replace("\\", "/").rstrip("/")

    # Must start with /downloads/... (fast + safe)
    if not (s == dr or s.startswith(dr + "/")):
        return None

    rel = s[len(dr):].lstrip("/")
    if not rel:
        return None

    ext = os.path.splitext(rel)[1].lower()
    if not ext:
        return None
    if ext not in MEDIA_EXTS:
        return None

    return rel


def ingest_task_log(conn: sqlite3.Connection, task_slug: str, log_path: str, *, full_rescan: bool = False) -> Tuple[int, int]:
    """
    Ingest one task's logs.txt.
    Returns (matched_lines, new_unique_inserts).
    """
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

    # Always update offset record
    def _upsert_offset(offset: int):
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
        _upsert_offset(start_offset)
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

        # Try insert unique
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

    _upsert_offset(end_offset)
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


def get_random_media_paths(conn: sqlite3.Connection, n: int) -> List[str]:
    rows = conn.execute(
        "SELECT path FROM media ORDER BY RANDOM() LIMIT ?",
        (int(n),)
    ).fetchall()
    return [r[0] for r in rows]


def get_mediawall_status(conn: sqlite3.Connection) -> dict:
    count = conn.execute("SELECT COUNT(*) FROM media").fetchone()[0]
    last_ingest = conn.execute("SELECT value FROM meta WHERE key='last_ingest'").fetchone()
    last_ingest = last_ingest[0] if last_ingest else None
    return {"count": int(count), "last_ingest": last_ingest}

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
    flash(
        f"Media wall updated. Tasks: {stats['tasks_seen']}, matched lines: {stats['matched']}, new items: {stats['inserted']}. "
        f"Total indexed: {status['count']}.",
        "success"
    )
    return redirect(url_for("home"))


@app.route("/mediawall/rebuild_full", methods=["POST"])
def mediawall_rebuild_full():
    conn = _open_media_db()
    stats = ingest_all_task_logs(conn, full_rescan=True)
    status = get_mediawall_status(conn)
    conn.close()
    flash(
        f"Media wall FULL reparse done. Tasks: {stats['tasks_seen']}, matched lines: {stats['matched']}, new items: {stats['inserted']}. "
        f"Total indexed: {status['count']}.",
        "success"
    )
    return redirect(url_for("home"))

# ---------------------------------------------------------------------
# Home page (NO downloads scanning; uses SQLite media index)
# ---------------------------------------------------------------------

@app.route("/")
def home():
    tasks = load_tasks()

    # Build media wall rows from SQLite (fast; no /downloads enumeration)
    conn = _open_media_db()
    paths = get_random_media_paths(conn, MEDIA_WALL_ITEMS)
    conn.close()

    # Convert to /media/<subpath> URLs for the template
    urls = [url_for("media_file", subpath=p) for p in paths]
    has_media = len(urls) > 0

    # Split into 3 rows (template expects recent_rows)
    recent_rows = [[] for _ in range(MEDIA_WALL_ROWS)]
    for i, u in enumerate(urls):
        recent_rows[i % MEDIA_WALL_ROWS].append(u)

    return render_template(
        "home.html",
        tasks_count=len(tasks),
        recent_rows=recent_rows,
        has_media=has_media,
    )

# ---------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------

@app.route("/tasks", methods=["GET", "POST"])
def tasks():
    if request.method == "POST":
        # IMPORTANT: do NOT touch /downloads here (slow mount might hang).
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

    return render_template("config.html", config_text=config_text, config_path=CONFIG_FILE)

# ---------------------------------------------------------------------
# Task actions
# ---------------------------------------------------------------------

def run_task_background(task_folder: str):
    # Only touch /downloads when actually running downloads
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
        # Update wall index from this task's new log lines (does NOT touch /downloads)
        if MEDIA_WALL_AUTO_INGEST_ON_TASK_END:
            try:
                slug = os.path.basename(task_folder.rstrip("/"))
                conn = _open_media_db()
                ingest_task_log(conn, slug, logs_path, full_rescan=False)
                conn.close()
            except Exception as exc:
                app.logger.warning("Media wall ingest failed for %s: %s", task_folder, exc)

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

        # Touch /downloads only when running
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
# Static media route
# ---------------------------------------------------------------------

@app.route("/media/<path:subpath>")
def media_file(subpath):
    # This will touch /downloads; only called when the browser requests a file.
    ensure_data_dirs(ensure_downloads=True)
    return send_from_directory(DOWNLOADS_ROOT, subpath)

# ---------------------------------------------------------------------
# Main (dev only)
# ---------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
