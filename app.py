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

from flask import (
    Flask, render_template, request,
    redirect, url_for, flash, send_from_directory
)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")

# Base data directories
# DATA_DIR is kept for backwards-compatibility but not used to create /data
DATA_DIR = os.environ.get("DATA_DIR", "/data")

# Allow overriding with TASKS_DIR / CONFIG_DIR envs (for Unraid-style mappings)
TASKS_ROOT = os.environ.get("TASKS_DIR") or os.path.join(DATA_DIR, "tasks")
CONFIG_ROOT = os.environ.get("CONFIG_DIR") or os.path.join(DATA_DIR, "config")  # global gallery-dl config

# Downloads root (separate volume)
DOWNLOADS_ROOT = os.environ.get("DOWNLOADS_DIR", "/downloads")

CONFIG_FILE = os.path.join(CONFIG_ROOT, "gallery-dl.conf")

DEFAULT_CONFIG_URL = os.environ.get(
    "GALLERYDL_DEFAULT_CONFIG_URL",
    "https://raw.githubusercontent.com/mikf/gallery-dl/master/docs/gallery-dl.conf",
)

# Media extensions for the recent downloads wall
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
VIDEO_EXTS = {".mp4", ".webm", ".mkv"}
MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS


def slugify(name: str) -> str:
    """Very simple slug: lowercase, spaces -> -, remove non-alphanum/-."""
    name = name.strip().lower()
    name = re.sub(r"\s+", "-", name)
    name = re.sub(r"[^a-z0-9-]+", "", name)
    return name or "task"


def ensure_data_dirs():
    """Ensure base directories exist."""
    # Do NOT try to create /data when running as non-root inside the container.
    os.makedirs(TASKS_ROOT, exist_ok=True)
    os.makedirs(CONFIG_ROOT, exist_ok=True)
    os.makedirs(DOWNLOADS_ROOT, exist_ok=True)


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
    ensure_data_dirs()

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


def get_recent_media(limit: int = 200, max_top_dirs: int = 30, max_age_days: int = 30):
    """
    Scan DOWNLOADS_ROOT for recent media files and return the newest ones.

    To avoid crawling millions of files on every page load:
      - We only look at the most recently modified top-level directories.
      - Within those, we prune subdirectories older than max_age_days.
    """
    items = []

    if not os.path.isdir(DOWNLOADS_ROOT):
        return items

    now = dt.datetime.now().timestamp()
    max_age_seconds = max_age_days * 24 * 60 * 60
    cutoff = now - max_age_seconds

    # 1) Find top-level directories under /downloads, sorted by mtime (newest first)
    top_dirs = []
    try:
        for entry in os.scandir(DOWNLOADS_ROOT):
            if not entry.is_dir(follow_symlinks=False):
                continue
            try:
                mtime = entry.stat().st_mtime
            except OSError:
                continue
            top_dirs.append((mtime, entry.path))
    except FileNotFoundError:
        return items

    top_dirs.sort(key=lambda x: x[0], reverse=True)
    top_dirs = [p for _, p in top_dirs[:max_top_dirs]]

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

            # Remove pruned dirs from the traversal
            for d in pruned_dirs:
                dirs.remove(d)

            for fname in files:
                ext = os.path.splitext(fname)[1].lower()
                if ext not in MEDIA_EXTS:
                    continue

                full_path = os.path.join(root, fname)
                try:
                    mtime = os.path.getmtime(full_path)
                except OSError:
                    continue

                rel_path = os.path.relpath(full_path, DOWNLOADS_ROOT).replace("\\", "/")
                items.append({
                    "rel_path": rel_path,
                    "filename": fname,
                    "mtime": mtime,
                    "is_image": ext in IMAGE_EXTS,
                })

    # Newest first
    items.sort(key=lambda x: x["mtime"], reverse=True)
    items = items[:limit]

    # Optional human-readable timestamp
    for item in items:
        item["mtime_readable"] = dt.datetime.fromtimestamp(item["mtime"]).isoformat(
            sep=" ", timespec="seconds"
        )

    return items


@app.route("/")
def home():
    tasks = load_tasks()
    recent_media = get_recent_media(limit=90)
    # Distribute items across 3 rows: 0,3,6... / 1,4,7... / 2,5,8...
    recent_rows = [
        recent_media[0::3],
        recent_media[1::3],
        recent_media[2::3],
    ]
    has_media = len(recent_media) > 0
    return render_template(
        "home.html",
        tasks_count=len(tasks),
        recent_rows=recent_rows,
        has_media=has_media,
    )


@app.route("/tasks", methods=["GET", "POST"])
def tasks():
    ensure_data_dirs()

    if request.method == "POST":
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

        # Ensure downloads root exists (config will handle subdirs)
        os.makedirs(DOWNLOADS_ROOT, exist_ok=True)

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

    tasks_list = load_tasks()
    return render_template("tasks.html", tasks=tasks_list)


@app.route("/config", methods=["GET", "POST"])
def config_page():
    """View and edit the global gallery-dl config file."""
    ensure_data_dirs()
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


def run_task_background(task_folder: str):
    """Background worker to run gallery-dl for a given task folder."""
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
    ensure_data_dirs()
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


@app.route("/media/<path:subpath>")
def media_file(subpath):
    """Serve files from the /downloads volume."""
    return send_from_directory(DOWNLOADS_ROOT, subpath)


if __name__ == "__main__":
    # For local dev; in Docker we use gunicorn
    app.run(host="0.0.0.0", port=5000, debug=True)
