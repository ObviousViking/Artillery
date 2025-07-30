import os
import time
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

TASKS_DIR = Path("/tasks")
RUNNER_SCRIPT = Path("/var/www/html/runner-scheduled.py")
CHECK_INTERVAL = 60  # seconds
LOG_PATH = Path("/logs/watcher.log")

# Ensure /logs directory exists
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

def log(msg):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    message = f"[Watcher] {msg}"
    print(message)
    with open(LOG_PATH, "a", encoding="utf-8") as log_file:
        log_file.write(f"{message}\n")

def clear_stale_lockfiles():
    log("Clearing stale lockfiles...")
    removed = 0
    for task_dir in TASKS_DIR.iterdir():
        if task_dir.is_dir():
            lockfile = task_dir / "lockfile"
            if lockfile.exists():
                try:
                    lockfile.unlink()
                    removed += 1
                except Exception as e:
                    log(f"  - Failed to remove lockfile in '{task_dir.name}': {e}")
    log(f"Cleared {removed} stale lockfile(s).\n")

def read_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception as e:
        log(f"  - Error reading {path.name}: {e}")
        return None

def parse_last_run(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return datetime.strptime(f.read().strip(), "%Y-%m-%d %H:%M:%S")
    except:
        return None

def should_run(interval_minutes, last_run, now):
    if last_run is None:
        return True
    return now >= last_run + timedelta(minutes=interval_minutes)

def main():
    log("Starting up watcher...")
    clear_stale_lockfiles()

    while True:
        now = datetime.now()
        log(f"Scanning tasks at {now.strftime('%Y-%m-%d %H:%M:%S')}")
        found_task = False

        for task_dir in TASKS_DIR.iterdir():
            if not task_dir.is_dir():
                continue

            found_task = True
            log(f" - Scanning task: {task_dir.name}")

            interval_file = task_dir / "interval.txt"
            command_file = task_dir / "command.txt"
            paused_file = task_dir / "paused.txt"
            lockfile = task_dir / "lockfile"
            last_run_file = task_dir / "last_run.txt"

            if paused_file.exists():
                log("   > paused.txt found - skipping task")
                continue

            if lockfile.exists():
                log("   > lockfile present - task already running")
                continue

            interval_str = read_file(interval_file)
            if not interval_str or not interval_str.isdigit():
                log("   > Invalid or missing interval.txt - skipping")
                continue

            interval = int(interval_str)
            command = read_file(command_file)
            if not command or not command.startswith("gallery-dl"):
                log("   > Invalid or missing command - skipping")
                continue

            last_run = parse_last_run(last_run_file)
            if should_run(interval, last_run, now):
                log("   ✓ Task is scheduled to run - passing to runner")
                try:
                    log(f"    > Executing: /opt/venv/bin/python3 /var/www/html/runner-task.py {task_dir}")

                    subprocess.Popen(["/opt/venv/bin/python3", "/var/www/html/runner-task.py", str(task_dir)])
                except Exception as e:
                    log(f"   - Error launching task: {e}")
            else:
                log("   ✗ Task not scheduled to run now")

        if not found_task:
            log("No tasks found in /tasks directory.")

        next_scan = now + timedelta(seconds=CHECK_INTERVAL)
        log(f"Scan complete. Next scan at {next_scan.strftime('%Y-%m-%d %H:%M:%S')}.\n")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
