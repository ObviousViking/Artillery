import os
from datetime import datetime

from croniter import croniter

from task_runtime import ensure_data_dirs, TASKS_ROOT, read_text, run_task_background


def should_run_now(cron_expr: str, now: datetime) -> bool:
    """
    Return True if the given cron expression matches the current time.
    This is evaluated per minute.
    """
    cron_expr = cron_expr.strip()
    if not cron_expr:
        return False
    try:
        return croniter.match(cron_expr, now)
    except Exception:
        return False


def main():
    ensure_data_dirs()
    now = datetime.now()

    if not os.path.isdir(TASKS_ROOT):
        return

    try:
        entries = list(os.scandir(TASKS_ROOT))
    except Exception:
        entries = []

    for entry in sorted(entries, key=lambda e: e.name):
        if not entry.is_dir():
            continue
        slug = entry.name
        task_folder = entry.path

        cron_path = os.path.join(task_folder, "cron.txt")
        cron_expr = read_text(cron_path)
        if not cron_expr:
            continue

        paused_path = os.path.join(task_folder, "paused")
        if os.path.exists(paused_path):
            continue

        lock_path = os.path.join(task_folder, "lock")
        if os.path.exists(lock_path):
            continue

        if not should_run_now(cron_expr, now):
            continue

        print(f"[scheduler] {now.isoformat()} - running task '{slug}' with cron '{cron_expr}'")

        # Create lock atomically to avoid races
        try:
            open(lock_path, "x").close()
        except FileExistsError:
            continue
        run_task_background(task_folder)


if __name__ == "__main__":
    main()
