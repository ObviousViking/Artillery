import os
import time
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from croniter import croniter

TASKS_DIR = Path("/tasks")
RUNNER_SCRIPT = Path("/var/www/html/runner-scheduled.py")
CHECK_INTERVAL = 60  # seconds
LOG_PATH = Path("/logs/watcher.log")

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

def is_valid_cron(expr):
    try:
        croniter(expr)
        return True
    except:
        return False

def should_run(cron_expr, now, last_run):
    try:
        if last_run is None:
            # Consider any time in the last CHECK_INTERVAL seconds
            fallback = now - timedelta(seconds=CHECK_INTERVAL)
            itr = croniter(cron_expr, fallback)
        else:
            itr = croniter(cron_expr, last_run)
        next_time = itr.get_next(datetime)
        return last_run is None or (last_run <= next_time <= now)
    except Exception as e:
        return False


def main():
    log("Starting up watcher...")
    clear_stale_lockfiles()
    last_check = datetime.now()

    while True:
        now = datetime.now()
        log(f"Scanning tasks at {now.strftime('%Y-%m-%d %H:%M:%S')}")
        found_task = False

        for task_dir in TASKS_DIR.iterdir():
            if not task_dir.is_dir():
                continue

            found_task = True
            log(f" - Scanning task: {task_dir.name}")

            schedule_file = task_dir / "schedule.txt"
            command_file = task_dir / "command.txt"
            paused_file = task_dir / "paused.txt"
            lockfile = task_dir / "lockfile"

            if paused_file.exists():
                log("   > paused.txt found - skipping task")
                continue

            if lockfile.exists():
                log("   > lockfile present - task already running")
                continue

            cron_expr = read_file(schedule_file)
            if not cron_expr:
                log("   > schedule.txt missing or unreadable - skipping")
                continue

            log(f"   > Parsing cron: '{cron_expr}'")
            if not is_valid_cron(cron_expr):
                log("   > Invalid cron expression - skipping")
                continue

            log("   > Cron is valid")

            command = read_file(command_file)
            if not command or not command.startswith("gallery-dl"):
                log("   > Invalid or missing command - skipping")
                continue

            if should_run(cron_expr, now, last_check):
                log("   ✓ Task is scheduled to run - passing to runner")
                try:
                    subprocess.Popen([sys.executable, str(RUNNER_SCRIPT), str(task_dir)], cwd=str(task_dir))
                except Exception as e:
                    log(f"   - Error launching task: {e}")
            else:
                log("   ✗ Task not scheduled to run now")

        if not found_task:
            log("No tasks found in /tasks directory.")

        next_scan = now + timedelta(seconds=CHECK_INTERVAL)
        log(f"Scan complete. Next scan at {next_scan.strftime('%Y-%m-%d %H:%M:%S')}.\n")
        time.sleep(CHECK_INTERVAL)
        last_check = now

if __name__ == "__main__":
    main()
