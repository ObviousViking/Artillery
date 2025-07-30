import os
import time
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from croniter import croniter

TASKS_DIR = Path(__file__).resolve().parent / "tasks"
CHECK_INTERVAL = 60  # seconds


def log(msg):
    print(f"[Watcher] {msg}")


def clear_stale_lockfiles():
    log("Clearing stale lockfiles...")
    removed = 0
    for task_dir in TASKS_DIR.iterdir():
        if task_dir.is_dir():
            lockfile = task_dir / "lockfile"
            if lockfile.exists():
                lockfile.unlink()
                removed += 1
    log(f"Cleared {removed} stale lockfile(s).\n")


def parse_schedule(schedule_file):
    try:
        with open(schedule_file, "r", encoding="utf-8") as f:
            line = f.read().strip()
            if '|' not in line:
                return None, None
            cron_expr, cmd = map(str.strip, line.split('|', 1))
            return cron_expr, cmd
    except Exception as e:
        log(f"Error reading {schedule_file}: {e}")
        return None, None


def should_run(cron_expr, now, last_check):
    try:
        itr = croniter(cron_expr, last_check)
        next_time = itr.get_next(datetime)
        return last_check <= next_time <= now
    except Exception:
        return False


def main():
    log("Starting up...")
    clear_stale_lockfiles()
    last_check = datetime.now()

    while True:
        now = datetime.now()
        next_scan_time = now + timedelta(seconds=CHECK_INTERVAL)
        log(f"Scanning tasks at {now.strftime('%Y-%m-%d %H:%M:%S')}")

        for task_dir in TASKS_DIR.iterdir():
            if not task_dir.is_dir():
                continue

            schedule_file = task_dir / "schedule.txt"
            paused_file = task_dir / "paused.txt"
            lockfile = task_dir / "lockfile"

            if not schedule_file.exists():
                continue
            if paused_file.exists() or lockfile.exists():
                continue

            cron_expr, command = parse_schedule(schedule_file)
            if not cron_expr or not command:
                continue

            if should_run(cron_expr, now, last_check):
                log(f"[✓] Triggering '{task_dir.name}'")
                try:
                    subprocess.Popen([sys.executable, "runner.py", command])
                except Exception as e:
                    log(f"Error running task '{task_dir.name}': {e}")

        duration = (datetime.now() - now).total_seconds()
        log(f"Scan complete in {duration:.2f}s. Next scan at {next_scan_time.strftime('%Y-%m-%d %H:%M:%S')}. Sleeping...\n")
        time.sleep(CHECK_INTERVAL)
        last_check = now


if __name__ == "__main__":
    main()