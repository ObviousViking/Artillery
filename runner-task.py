#!/usr/bin/env python3
import os
import sys
import subprocess
from datetime import datetime

def read_command_file(task_path):
    command_path = os.path.join(task_path, "command.txt")
    if not os.path.isfile(command_path):
        print(f"Error: command.txt not found in {task_path}", file=sys.stderr)
        sys.exit(1)
    with open(command_path, "r", encoding="utf-8") as f:
        return f.read().strip()

def update_last_run(task_path):
    timestamp_path = os.path.join(task_path, "last_run.txt")
    with open(timestamp_path, "w", encoding="utf-8") as f:
        f.write(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

def main():
    if len(sys.argv) < 2:
        print("Usage: runner-task.py <taskname>", file=sys.stderr)
        sys.exit(1)

    task_name = sys.argv[1]
    task_path = os.path.join("/tasks", task_name)

    if not os.path.isdir(task_path):
        print(f"Error: Task folder not found: {task_name}", file=sys.stderr)
        sys.exit(1)

    lockfile = os.path.join(task_path, "lockfile")
    if os.path.exists(lockfile):
        print(f"Task already running: {task_name}", file=sys.stderr)
        sys.exit(0)

    try:
        with open(lockfile, 'w') as f:
            f.write("Running")
    except Exception as e:
        print(f"Error creating lockfile: {e}", file=sys.stderr)
        sys.exit(1)

    command = read_command_file(task_path)
    args = command.strip().split()

    # REMOVE the whole block that cleans/inserts --dest/--config

    print(f"Executing: {' '.join(args)}")

    try:
        result = subprocess.run(args, cwd=task_path, capture_output=True, text=True, check=True)
        print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
    except subprocess.CalledProcessError as e:
        print(f"Error running gallery-dl: {e.stderr}", file=sys.stderr)
    finally:
        if os.path.exists(lockfile):
            os.remove(lockfile)
        update_last_run(task_path)


if __name__ == "__main__":
    main()
