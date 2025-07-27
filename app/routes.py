from flask import Blueprint, render_template, request, redirect, url_for, flash, send_from_directory
from pathlib import Path
import os
import json
import subprocess
import traceback
from app.scheduler import scheduler
from flask import send_from_directory


# ✅ Define once and keep it at the top
main = Blueprint('main', __name__)


# ---------------------- Routes ----------------------

@app.route("/downloads/<path:filename>")
def serve_download(filename):
    return send_from_directory("/downloads", filename)

@main.route("/")
def homepage():
    image_extensions = {".jpg", ".jpeg", ".png"}
    image_files = []

    for root, _, files in os.walk("/downloads"):
        for name in files:
            ext = Path(name).suffix.lower()
            if ext in image_extensions:
                full_path = Path(root) / name
                rel_path = full_path.relative_to("/downloads")
                image_files.append((full_path.stat().st_mtime, str(rel_path)))

    image_files.sort(reverse=True)
    recent_images = [path for _, path in image_files[:20]]

    return render_template("index.html", recent_images=recent_images)

@main.route('/config', methods=['GET', 'POST'])
def config_editor():
    config_path = '/config/config.json'
    if request.method == 'POST':
        new_content = request.form.get('config_content')
        try:
            json.loads(new_content)
            with open(config_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            flash("Config updated successfully!", "success")
        except json.JSONDecodeError:
            flash("Invalid JSON. Please fix errors before saving.", "error")
    with open(config_path, 'r', encoding='utf-8') as f:
        current_content = f.read()
    return render_template('config.html', config=current_content)



@main.route('/new-task', methods=['GET', 'POST'])
def new_task():
    if request.method == "POST":
        task_name = request.form.get("task_name", "").strip()
        url_list = request.form.get("url_list", "").strip()
        schedule = request.form.get("schedule", "").strip()

        if not task_name or not url_list:
            return "Task name and URL list are required.", 400

        task_path = Path(f"/tasks/{task_name}")
        task_path.mkdir(parents=True, exist_ok=True)

        # Save URL list
        (task_path / "url_list.txt").write_text(url_list)

        # Save schedule
        (task_path / "schedule.txt").write_text(schedule)

        # Determine flags
        flags = [
            "-i url_list.txt",
            "-f /O",
            "-d /downloads",
            "--no-input",
            "--verbose",
            "--write-log log.txt",
            "--no-part"
        ]

        # Download archive handling (use full path)
        use_archive = request.form.get("use_download_archive") == "on"
        if use_archive:
            archive_path = task_path / f"{task_name}.sqlite"
            flags.append(f'--download-archive "{archive_path}"')
            archive_path.touch()

        # Optional flags
        if request.form.get("use_cookies") == "on":
            flags.append("-C cookies.txt")

        # Named flags
        for field in ["retries", "limit_rate", "sleep", "sleep_request", "sleep_429", "sleep_extractor", "rename", "rename_to"]:
            value = request.form.get(field, "").strip()
            if value:
                flag = "--" + field.replace("_", "-")
                flags.append(f'{flag} {value}')

        # Checkbox flags
        for key in request.form.keys():
            if key.startswith("flag_"):
                flag_name = "--" + key.replace("flag_", "").replace("_", "-")
                flags.append(flag_name)

        # Save the command file
        full_command = "gallery-dl " + " ".join(flags)
        (task_path / "command.txt").write_text(full_command)

        return redirect(url_for('main.view_tasks'))

    return render_template("new_task.html")


@main.route('/tasks')
def view_tasks():
    try:
        tasks = []
        task_dir = Path("/tasks")

        for folder in sorted(task_dir.iterdir()):
            if folder.is_dir():
                task_name = folder.name
                task_path = folder
                command_path = folder / "command.txt"
                schedule_path = folder / "schedule.txt"
                log_path = folder / "log.txt"
                pause_path = folder / "paused.txt"

                command = command_path.read_text().strip() if command_path.exists() else "N/A"
                schedule = schedule_path.read_text().strip() if schedule_path.exists() else "N/A"
                has_log = log_path.exists()
                is_paused = pause_path.exists()

                tasks.append({
                    "name": task_name,
                    "command": command,
                    "schedule": schedule,
                    "status": "Paused" if is_paused else "Pending",
                    "next_run": "Unknown",
                    "has_log": has_log,
                    "is_paused": is_paused
                })

        return render_template("view_tasks.html", tasks=tasks)

    except Exception:
        traceback.print_exc()
        return "An error occurred. Check logs."


@main.route('/run/<task_name>', methods=['POST'])
def run_task(task_name):
    task_path = Path(f"/tasks/{task_name}")
    command_file = task_path / "command.txt"
    if not command_file.exists():
        flash(f"No command file found for {task_name}", "danger")
        return redirect(url_for('main.view_tasks'))

    command = command_file.read_text().strip()
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=task_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        print(f"[Manual Run] Output from {task_name}:\n{result.stdout}")
        flash(f"Task {task_name} ran successfully.", "success")
    except Exception as e:
        print(f"[Manual Run] Error running {task_name}: {e}")
        flash(f"Error running task {task_name}: {e}", "danger")

    return redirect(url_for('main.view_tasks'))  # ✅ Ensure we return something




@main.route('/download-log/<task_name>')
def download_log(task_name):
    try:
        task_path = os.path.join("/tasks", task_name)
        return send_from_directory(task_path, "log.txt", as_attachment=True)
    except Exception:
        traceback.print_exc()
        return "Error downloading log"



@main.route('/edit-task/<task_name>', methods=['GET', 'POST'])
def edit_task(task_name):
    task_path = Path(f"/tasks/{task_name}")
    if not task_path.exists():
        return f"Task '{task_name}' not found.", 404

    command_file = task_path / "command.txt"
    schedule_file = task_path / "schedule.txt"
    archive_file = task_path / f"{task_name}.sqlite"

    if request.method == "POST":
        # Save updated schedule
        new_schedule = request.form.get("schedule", "").strip()
        if new_schedule:
            schedule_file.write_text(new_schedule)

        # Update download archive flag
        use_archive = request.form.get("use_download_archive") == "on"
        if use_archive and not archive_file.exists():
            archive_file.touch()
        elif not use_archive and archive_file.exists():
            archive_file.unlink()

        # Rebuild command
        flags = [
            "-i url_list.txt",
            "-f /O",
            "-d /downloads",
            "--no-input",
            "--verbose",
            "--write-log log.txt",
            "--no-part"
        ]

        if use_archive:
            full_archive_path = str(archive_file)
            flags.append(f"--download-archive {full_archive_path}")

        command = "gallery-dl " + " ".join(flags)
        command_file.write_text(command)

        return redirect(url_for('main.view_tasks'))

    # Load current values
    current_schedule = schedule_file.read_text().strip() if schedule_file.exists() else ""
    has_archive = archive_file.exists()

    return render_template("edit_task.html", task_name=task_name, schedule=current_schedule, has_archive=has_archive)


@main.route('/delete-task/<task_name>', methods=['POST'])
def delete_task(task_name):
    task_path = Path(f"/tasks/{task_name}")
    if not task_path.exists():
        return f"Task '{task_name}' not found.", 404

    # Optional: delete the archive file if requested
    delete_archive = request.form.get("delete_archive") == "on"
    archive_file = task_path / f"{task_name}.sqlite"
    if delete_archive and archive_file.exists():
        archive_file.unlink()

    # Delete known files
    for fname in ["command.txt", "schedule.txt", "log.txt", "url_list.txt"]:
        fpath = task_path / fname
        if fpath.exists():
            fpath.unlink()

    # Finally, delete the entire task directory if it's now empty
    try:
        task_path.rmdir()
    except OSError:
        # Directory is not empty (e.g., leftover files), remove it recursively
        import shutil
        shutil.rmtree(task_path)

    return redirect(url_for("main.view_tasks"))



@main.route('/delete-archive/<task_name>', methods=['POST'])
def delete_archive(task_name):
    try:
        task_folder = Path(f"/tasks/{task_name}")
        archive_file = task_folder / f"{task_name}.sqlite"

        if archive_file.exists():
            archive_file.unlink()
            flash(f"Archive file deleted for task '{task_name}'", "success")
        else:
            flash(f"No archive file found for task '{task_name}'", "info")

    except Exception as e:
        traceback.print_exc()
        flash(f"Error deleting archive for '{task_name}': {e}", "error")

    return redirect(url_for('main.view_tasks'))




@main.route('/pause-task/<task_name>', methods=['POST'])
def pause_task(task_name):
    task_path = Path(f"/tasks/{task_name}")
    pause_file = task_path / "paused.txt"
    try:
        pause_file.touch(exist_ok=True)
        print(f"[Task] Paused '{task_name}'")
    except Exception as e:
        print(f"[Task] Failed to pause '{task_name}': {e}")
    return redirect(url_for('main.view_tasks'))

@main.route('/resume/<task_name>', methods=['POST'])
def resume_task(task_name):
    task_path = Path(f"/tasks/{task_name}")
    pause_file = task_path / "paused.txt"

    try:
        if pause_file.exists():
            pause_file.unlink()
            print(f"[Task Resume] {task_name} resumed.")

        # Reschedule it
        schedule_file = task_path / "schedule.txt"
        if not schedule_file.exists():
            return f"Schedule for '{task_name}' not found", 404

        schedule = schedule_file.read_text().strip().lower()
        from app.scheduler import scheduler
        from apscheduler.triggers.interval import IntervalTrigger

        # Remove old job if exists
        job_id = f"task_{task_name}"
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)

        # Re-add job
        if schedule == "every 1 minute":
            scheduler.add_job(
                run_task,
                IntervalTrigger(minutes=1),
                args=[task_name],
                id=job_id,
                replace_existing=True,
                misfire_grace_time=60
            )
            print(f"[Scheduler] Rescheduled '{task_name}' after resume")

        return redirect(url_for("main.view_tasks"))

    except Exception:
        traceback.print_exc()
        return "Failed to resume task", 500



@main.route('/fetch-default-config', methods=['POST'])
def fetch_default_config():
    try:
        from app import fetch_default_config as fetch_func
        fetch_func()
        flash("Default config downloaded successfully.", "success")
    except Exception as e:
        flash(f"Failed to fetch default config: {str(e)}", "danger")
    return redirect(url_for('main.config'))
