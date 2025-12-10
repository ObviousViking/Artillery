#!/usr/bin/env python3
import os
import subprocess
from datetime import datetime
from croniter import croniter

TASKS_DIR = "/tasks"
RUNNER_SCRIPT = os.environ.get("RUNNER_TASK", "/app/runner-task.py")
PYTHON_BIN = os.environ.get("PYTHON_BIN", "/usr/local/bin/python3")

def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")

def is_due(schedule, last_run_time):
    now = datetime.now()
    try:
        itr = croniter(schedule, last_run_time or now)
        next_run = itr.get_next(datetime)
        return next_run <= now
    except Exception as e:
        log(f"Invalid cron expression '{schedule}': {e}")
        return False

def parse_last_run(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return datetime.strptime(f.read().strip(), "%Y-%m-%d %H:%M:%S")
    except:
        return None

def main():
    if not os.path.isdir(TASKS_DIR):
        log(f"Tasks directory not found: {TASKS_DIR}")
        return

    for task_name in os.listdir(TASKS_DIR):
        task_path = os.path.join(TASKS_DIR, task_name)
        if not os.path.isdir(task_path):
            continue

        schedule_file = os.path.join(task_path, "schedule.txt")
        paused_file = os.path.join(task_path, "paused.txt")
        lockfile = os.path.join(task_path, "lockfile")
        last_run_file = os.path.join(task_path, "last_run.txt")

        if not os.path.exists(schedule_file):
            continue
        if os.path.exists(paused_file):
            log(f"[{task_name}] Skipped (paused)")
            continue
        if os.path.exists(lockfile):
            log(f"[{task_name}] Skipped (already running)")
            continue

        try:
            with open(schedule_file, "r", encoding="utf-8") as f:
                cron_expr = f.read().strip()
        except Exception as e:
            log(f"[{task_name}] Failed to read schedule.txt: {e}")
            continue

        last_run = parse_last_run(last_run_file)

        if not is_due(cron_expr, last_run):
            log(f"[{task_name}] Not due to run")
            continue

        log(f"[{task_name}] Launching scheduled task")
        try:
            subprocess.Popen([PYTHON_BIN, RUNNER_SCRIPT, task_path])
        except Exception as e:
            log(f"[{task_name}] Failed to launch: {e}")

if __name__ == "__main__":
    main()
