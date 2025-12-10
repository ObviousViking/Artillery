import os
from datetime import datetime

from croniter import croniter

from app import (
    ensure_data_dirs,
    TASKS_ROOT,
    read_text,
    run_task_background,
)


def should_run_now(cron_expr: str, now: datetime) -> bool:
    """
    Return True if the given cron expression matches the current time.
    This is evaluated per minute.
    """
    cron_expr = cron_expr.strip()
    if not cron_expr:
        return False
    return croniter.match(cron_expr, now)


def main():
    ensure_data_dirs()
    now = datetime.now()

    if not os.path.isdir(TASKS_ROOT):
        return

    for slug in sorted(os.listdir(TASKS_ROOT)):
        task_folder = os.path.join(TASKS_ROOT, slug)
        if not os.path.isdir(task_folder):
            continue

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

        open(lock_path, "w").close()
        run_task_background(task_folder)


if __name__ == "__main__":
    main()
