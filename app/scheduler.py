from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from pathlib import Path
from datetime import datetime
import subprocess
import time
import os
import logging
from logging.handlers import RotatingFileHandler

scheduler = BackgroundScheduler(timezone="UTC")

log_dir = "/config/logs"
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, "scheduler.log")

logger = logging.getLogger("scheduler")
logger.setLevel(logging.INFO)
if not logger.handlers:
    file_handler = RotatingFileHandler(log_file, maxBytes=1024*1024, backupCount=3)
    stream_handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] %(message)s")
    file_handler.setFormatter(formatter)
    stream_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)

def log(msg):
    logger.info(msg)

def run_task(task_name):
    log(f"[Scheduler] Running scheduled task: {task_name}")
    task_path = Path(f"/tasks/{task_name}")
    paused_file = task_path / "paused.txt"

    if paused_file.exists():
        log(f"[Scheduler] Task '{task_name}' is paused. Skipping.")
        return

    command_file = task_path / "command.txt"
    if not command_file.exists():
        log(f"[Scheduler] Missing command.txt for {task_name}")
        return

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
        log(f"[Scheduler] Output from {task_name}:\n{result.stdout}")
    except Exception as e:
        log(f"[Scheduler] Error running {task_name}: {e}")

def refresh_tasks():
    log("[Scheduler] Reloading task definitions")

    task_dir = Path("/tasks")

    # Remove all jobs except the auto-refresh one
    for job in scheduler.get_jobs():
        if job.id != "reload_tasks":
            log(f"[Scheduler] Removing job: {job.id}")
            scheduler.remove_job(job.id)

    # Re-scan all folders
    for folder in sorted(task_dir.iterdir()):
        if folder.is_dir():
            task_name = folder.name
            schedule_path = folder / "schedule.txt"
            if schedule_path.exists():
                cron_expr = schedule_path.read_text().strip()
                try:
                    trigger = CronTrigger.from_crontab(cron_expr)
                    scheduler.add_job(
                        run_task,
                        trigger=trigger,
                        args=[task_name],
                        id=task_name,
                        replace_existing=True
                    )
                    log(f"[Scheduler] Registered: {task_name} (cron: {cron_expr})")
                except Exception as e:
                    log(f"[Scheduler] Failed to register {task_name}: Invalid cron '{cron_expr}' — {e}")

def start_scheduler():
    log("[Scheduler] Starting scheduler...")

    if not scheduler.running:
        scheduler.start()
        log("[Scheduler] Scheduler started")
    else:
        log("[Scheduler] Scheduler already running")

    refresh_tasks()

    scheduler.add_job(refresh_tasks, IntervalTrigger(seconds=60), id="reload_tasks", replace_existing=True)

    try:
        while True:
            time.sleep(10)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()


def log(msg):
    log(f"[{datetime.utcnow().isoformat()}] {msg}")
