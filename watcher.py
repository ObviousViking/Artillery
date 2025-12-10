import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

CHECK_INTERVAL = int(os.environ.get("WATCH_INTERVAL", "60"))
TASKS_DIR = Path(os.environ.get("TASK_DIR", "/tasks"))
RUNNER_SCRIPT = Path(os.environ.get("RUNNER_TASK", "/app/runner_task.py"))
PYTHON_BIN = os.environ.get("PYTHON_BIN", sys.executable)
LOG_PATH = Path(os.environ.get("LOG_DIR", "/logs")) / "watcher.log"

LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


def log(msg: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    message = f"[Watcher] {msg}"
    print(message)
    with open(LOG_PATH, "a", encoding="utf-8") as log_file:
        log_file.write(f"{timestamp} {message}\n")


def clear_stale_lockfiles() -> None:
    log("Clearing stale lockfiles...")
    removed = 0
    for task_dir in TASKS_DIR.iterdir():
        if task_dir.is_dir():
            lockfile = task_dir / "lockfile"
            if lockfile.exists():
                try:
                    lockfile.unlink()
                    removed += 1
                except Exception as e:  # noqa: BLE001
                    log(f"  - Failed to remove lockfile in '{task_dir.name}': {e}")
    log(f"Cleared {removed} stale lockfile(s).\n")


def read_file(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception as e:  # noqa: BLE001
        log(f"  - Error reading {path.name}: {e}")
        return None


def parse_last_run(path: Path):
    try:
        return datetime.strptime(path.read_text(encoding="utf-8").strip(), "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def should_run(interval_minutes: int, last_run, now: datetime) -> bool:
    if last_run is None:
        return True
    return now >= last_run + timedelta(minutes=interval_minutes)


def main() -> None:
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
                    log(f"    > Executing: {PYTHON_BIN} {RUNNER_SCRIPT} {task_dir}")
                    subprocess.Popen([PYTHON_BIN, str(RUNNER_SCRIPT), str(task_dir)])
                except Exception as e:  # noqa: BLE001
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
