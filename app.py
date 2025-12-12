import os
import json  # unused for now, handy later
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


# ---------------------------------------------------------------------
# Base data directories
# ---------------------------------------------------------------------

# Allow overriding with TASKS_DIR / CONFIG_DIR envs (for Unraid-style mappings)
TASKS_ROOT = os.environ.get("TASKS_DIR") or "/tasks"
CONFIG_ROOT = os.environ.get("CONFIG_DIR") or "/config"   # global gallery-dl config
DOWNLOADS_ROOT = os.environ.get("DOWNLOADS_DIR") or "/downloads"

CONFIG_FILE = os.path.join(CONFIG_ROOT, "gallery-dl.conf")

DEFAULT_CONFIG_URL = os.environ.get(
    "GALLERYDL_DEFAULT_CONFIG_URL",
    "https://raw.githubusercontent.com/mikf/gallery-dl/master/docs/gallery-dl.conf",
)

# Media extensions (kept for future use, but NOT used on the home page right now)
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
VIDEO_EXTS = {".mp4", ".webm", ".mkv"}
MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS


# ---------------------------------------------------------------------
# Request timing (optional)
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

def slugify(name: str) -> str:
    """Very simple slug: lowercase, spaces -> -, remove non-alphanum/-."""
    name = name.strip().lower()
    name = re.sub(r"\s+", "-", name)
    name = re.sub(r"[^a-z0-9-]+", "", name)
    return name or "task"


def ensure_data_dirs(ensure_downloads: bool = False):
    """
    Ensure base directories exist.

    IMPORTANT:
    - We DO NOT touch /downloads unless explicitly asked to.
      This prevents the UI from hanging when /downloads is a huge/slow/stale mount.
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
    """Read a small text file, return stripped contents or None."""
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip() or None


def write_text(path: str, content: str):
    """Write a small text file (overwrite)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def load_tasks():
    """Scan TASKS_ROOT and build a list of task dicts from per-task folders."""
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
            "id": slug,               # we use slug as id
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
# Health check (never touches /downloads)
# ---------------------------------------------------------------------

@app.route("/healthz")
def healthz():
    return Response("ok\n", mimetype="text/plain")


# ---------------------------------------------------------------------
# Home page (NO filesystem scanning)
# ---------------------------------------------------------------------

@app.route("/")
def home():
    """
    Home page: show welcome text + task count.

    The media wall is disabled: we pass empty recent_rows and has_media=False
    so the template shows the "No recent downloads found yet." message without
    touching /downloads.
    """
    tasks = load_tasks()

    recent_rows = [[], [], []]
    has_media = False

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
        # Only touch /downloads when the user is actively creating/updating tasks
        ensure_data_dirs(ensure_downloads=True)

        name = request.form.get("name", "").strip()
        urls_text = request.form.get("urls", "").strip()
        schedule = request.form.get("schedule", "").strip()  # cron
        command = request.form.get("command", "").strip()

        if not name:
            flash("Task name is required.", "error")
            return redirect(url_for("tasks"))

        if not urls_text:
            flash("You need to provide at least one URL.", "error")
            return redirect(url_for("tasks"))

        # Folder based on task name
        slug = slugify(name)
        task_folder = os.path.join(TASKS_ROOT, slug)
        os.makedirs(task_folder, exist_ok=True)

        # Basic files
        write_text(os.path.join(task_folder, "name.txt"), name)
        write_text(os.path.join(task_folder, "urls.txt"), urls_text.strip() + "\n")

        if schedule:
            write_text(os.path.join(task_folder, "cron.txt"), schedule)
        else:
            cron_path = os.path.join(task_folder, "cron.txt")
            if os.path.exists(cron_path):
                os.remove(cron_path)

        # Fallback command if builder didn’t fill anything
        if not command:
            command = "gallery-dl --input-file urls.txt"

        # ensure the command has --config and --destination (-d) set correctly
        try:
            parts = shlex.split(command)
            if parts and parts[0] == "gallery-dl":
                has_config_flag = False
                has_dest_flag = False

                for p in parts:
                    if p in ("-c", "--config") or p.startswith("--config="):
                        has_config_flag = True
                    if p in ("-d", "--destination") or p.startswith("--destination="):
                        has_dest_flag = True

                insert_index = 1  # directly after 'gallery-dl'

                # Inject --config first (if missing)
                if not has_config_flag:
                    parts.insert(insert_index, "--config")
                    parts.insert(insert_index + 1, CONFIG_FILE)
                    insert_index += 2

                # Then inject -d / --destination /downloads (if missing)
                if not has_dest_flag:
                    parts.insert(insert_index, "--destination")
                    parts.insert(insert_index + 1, DOWNLOADS_ROOT)

                command = " ".join(shlex.quote(p) for p in parts)
        except ValueError:
            # If parsing fails, just leave command as-is; user can fix it manually.
            pass

        write_text(os.path.join(task_folder, "command.txt"), command)

        # Ensure logs.txt exists (even if empty)
        logs_path = os.path.join(task_folder, "logs.txt")
        if not os.path.exists(logs_path):
            write_text(logs_path, "")

        flash("Task created (or updated).", "success")
        return redirect(url_for("tasks"))

    # GET: never touch /downloads
    ensure_data_dirs(ensure_downloads=False)
    tasks_list = load_tasks()
    return render_template("tasks.html", tasks=tasks_list)


# ---------------------------------------------------------------------
# Config page (never touches /downloads)
# ---------------------------------------------------------------------

@app.route("/config", methods=["GET", "POST"])
def config_page():
    """View and edit the global gallery-dl config file."""
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
    """Background worker to run gallery-dl for a given task folder."""
    # If /downloads is slow/hung, this will only hang the background worker,
    # not your UI page loads.
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
    # Hard-wire config for safety
    env["GALLERY_DL_CONFIG"] = CONFIG_FILE
    # Ensure gallery-dl is on PATH for cron-launched processes
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
        if os.path.exists(lock_path):
            os.remove(lock_path)


@app.route("/tasks/<slug>/action", methods=["POST"])
def task_action(slug):
    """Handle per-task actions: run, pause/unpause, delete."""
    ensure_data_dirs(ensure_downloads=False)
    action = request.form.get("action")
    task_folder = os.path.join(TASKS_ROOT, slug)

    if not os.path.isdir(task_folder):
        flash("Task not found.", "error")
        return redirect(url_for("tasks"))

    # DELETE
    if action == "delete":
        try:
            shutil.rmtree(task_folder)
            flash(f"Task '{slug}' deleted.", "success")
        except Exception as exc:
            flash(f"Failed to delete task: {exc}", "error")
        return redirect(url_for("tasks"))

    # RUN (background)
    if action == "run":
        paused_path = os.path.join(task_folder, "paused")
        if os.path.exists(paused_path):
            flash("Task is paused. Unpause it before running.", "error")
            return redirect(url_for("tasks"))

        lock_path = os.path.join(task_folder, "lock")
        if os.path.exists(lock_path):
            flash("Task is already running.", "error")
            return redirect(url_for("tasks"))

        # Touch /downloads only when actually running a task
        ensure_data_dirs(ensure_downloads=True)

        # Create lock file immediately
        open(lock_path, "w").close()

        # Fire off a background thread
        t = threading.Thread(target=run_task_background, args=(task_folder,), daemon=True)
        t.start()

        flash("Task started in background. Check logs.txt for progress.", "success")
        return redirect(url_for("tasks"))

    # PAUSE / UNPAUSE
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
# Static media route (kept as before)
# ---------------------------------------------------------------------

@app.route("/media/<path:subpath>")
def media_file(subpath):
    """Serve files from the /downloads volume."""
    # Only touch /downloads if the user is actually requesting a file from it
    ensure_data_dirs(ensure_downloads=True)
    return send_from_directory(DOWNLOADS_ROOT, subpath)


# ---------------------------------------------------------------------
# Main (dev only)
# ---------------------------------------------------------------------

if __name__ == "__main__":
    # For local dev; in Docker we use gunicorn
    app.run(host="0.0.0.0", port=5000, debug=True)
